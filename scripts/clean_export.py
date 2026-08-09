#!/usr/bin/env python3
"""
Export a GE cath-lab .inf/.bin recording to analysis-ready CSV.

    python scripts/clean_export.py sample/SYNTH01              # cleaned, default settings
    python scripts/clean_export.py sample/SYNTH01 --raw        # untouched, decide later
    python scripts/clean_export.py sample/SYNTH01 --no-baseline --sat-threshold 4.5

Outputs land in <parent>/derived/ :
    <stem>_clean.csv | <stem>_raw.csv   full rate: timestamp, t_sec, every channel
    <stem>_..._trend.csv                one row per second: HR, pressures, validity
    <stem>_..._qc.txt                   every setting used + what each step removed

Every cleaning step is optional and every threshold is a flag, so a colleague can tune
in cath_viewer.html, copy the generated command, and reproduce it exactly in batch.

Removed samples are written as empty fields -- never zeros, never interpolated.
"""
import argparse
import re
import sys
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.ndimage import maximum_filter1d, median_filter
from scipy.signal import butter, filtfilt, find_peaks

ECG_LABELS = {'I', 'II', 'III', 'aVR', 'aVL', 'aVF',
              'V1', 'V2', 'V3', 'V4', 'V5', 'V6'}
RAIL_FRAC = 0.998        # fraction of observed full scale that counts as saturated
WRAP_COUNTS = 65536      # the pressure overflow is a clean 16-bit wrap


@contextmanager
def quiet():
    """All-NaN slices are expected here; keep every other warning visible."""
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        yield


@dataclass
class Config:
    """Everything the viewer can change. Defaults are the validated settings."""
    unwrap: bool = True
    sat_mask: bool = True
    sat_threshold: Optional[float] = None      # None -> derive from the data
    sat_pad_s: float = 0.012
    baseline: bool = True
    baseline_w1_s: float = 0.200               # > any QRS, so the median skips the beat
    baseline_w2_s: float = 0.600               # spans P-QRS-T
    press_pad_s: float = 0.25                  # transducer ringdown after a flush
    press_limits: dict = field(default_factory=lambda: {
        'default': (-40.0, 300.0), 'PCW': (-40.0, 150.0)})
    live_mask: bool = True
    live_block_s: float = 10.0
    live_rules: dict = field(default_factory=lambda: {   # (min pulse pressure, min med, max med)
        'default': (8.0, 30.0, 200.0), 'PCW': (3.0, -5.0, 45.0)})
    highpass: Optional[float] = None           # Hz, off by default
    lowpass: Optional[float] = None            # Hz, off by default

    @classmethod
    def raw(cls):
        return cls(unwrap=False, sat_mask=False, baseline=False,
                   live_mask=False, press_limits={}, press_pad_s=0.0)

    def limits_for(self, label):
        if not self.press_limits:
            return (-np.inf, np.inf)
        return self.press_limits.get(label, self.press_limits.get(
            'default', (-np.inf, np.inf)))

    def rules_for(self, label):
        return self.live_rules.get(label, self.live_rules.get(
            'default', (0.0, -np.inf, np.inf)))

    def as_flags(self):
        d, out = Config(), []
        if not self.unwrap:
            out.append('--no-unwrap')
        if not self.sat_mask:
            out.append('--no-sat-mask')
        if self.sat_threshold is not None:
            out.append(f'--sat-threshold {self.sat_threshold:g}')
        if self.sat_pad_s != d.sat_pad_s:
            out.append(f'--sat-pad {self.sat_pad_s:g}')
        if not self.baseline:
            out.append('--no-baseline')
        if self.baseline_w1_s != d.baseline_w1_s:
            out.append(f'--baseline-window {self.baseline_w1_s:g}')
        if not self.live_mask:
            out.append('--no-live-mask')
        if self.press_pad_s != d.press_pad_s:
            out.append(f'--press-pad {self.press_pad_s:g}')
        for k, (lo, hi) in sorted(self.press_limits.items()):
            if d.press_limits.get(k) != (lo, hi):
                out.append(f'--press-limit {k}={lo:g}:{hi:g}')
        if self.highpass:
            out.append(f'--highpass {self.highpass:g}')
        if self.lowpass:
            out.append(f'--lowpass {self.lowpass:g}')
        return ' '.join(out)


# ------------------------------------------------------------------- input --
def read_inf(path: Path):
    """Parse the GE .inf sidecar into (meta dict, channel labels)."""
    meta, labels = {}, []
    for line in path.read_text(encoding='latin-1').splitlines():
        m = re.match(r'\s*(\d+)\s+(\S+)\s*$', line)
        if m:
            labels.append(m.group(2))
        elif '=' in line:
            k, v = line.split('=', 1)
            meta[k.strip()] = v.strip()
    return meta, labels


def parse_header(stem: Path):
    meta, labels = read_inf(stem.with_suffix('.inf'))
    n = int(meta['Points for Each Channel'])
    c = int(meta['Number of Channel'])
    fs = int(re.search(r'\d+', meta['Data Sampling Rate']).group())
    if len(labels) != c:
        sys.exit(f'.inf lists {len(labels)} labels but declares {c} channels')

    nbytes = stem.with_suffix('.bin').stat().st_size
    if nbytes != n * c * 8:
        sys.exit(f'.bin is {nbytes} bytes, expected {n * c * 8} '
                 f'({n} x {c} x 8). Refusing to guess the layout.')

    start = None
    for key in ('Start Time', 'Date'):
        if key in meta:
            try:
                start = datetime.strptime(meta[key].strip(), '%m/%d/%Y %I:%M:%S %p')
                break
            except ValueError:
                continue
    return meta, labels, n, c, fs, start


def clamp_idx(v, n):
    return int(min(max(0, round(v)), n))


def lsb_of(x: np.ndarray) -> float:
    """Smallest non-zero gap between distinct values = the ADC step."""
    u = np.unique(x[::97])
    d = np.diff(u)
    d = d[d > 1e-9]
    return float(d.min()) if d.size else 1.0


# ---------------------------------------------------------------- cleaning --
def bandlimit(x, fs, cfg):
    """Optional high/low-pass. NaNs are held out and restored afterwards."""
    if not (cfg.highpass or cfg.lowpass):
        return x
    hole = ~np.isfinite(x)
    y = np.nan_to_num(x, nan=float(np.nanmedian(x)) if (~hole).any() else 0.0)
    nyq = fs / 2.0
    if cfg.highpass:
        b, a = butter(2, min(cfg.highpass / nyq, 0.99), 'high')
        y = filtfilt(b, a, y)
    if cfg.lowpass:
        b, a = butter(4, min(cfg.lowpass / nyq, 0.99), 'low')
        y = filtfilt(b, a, y)
    y[hole] = np.nan
    return y


def clean_pressure(x, fs, label, cfg, qc):
    """Unwrap the 16-bit overflow, then NaN out artefact and not-live stretches."""
    steps = []
    if cfg.unwrap:
        lsb = lsb_of(x)
        wrapped = x < -1000.0
        if wrapped.any():
            x[wrapped] += WRAP_COUNTS * lsb
            steps.append(f'unwrapped {int(wrapped.sum())} (+{WRAP_COUNTS * lsb:.1f} mmHg)')

    lo, hi = cfg.limits_for(label)
    bad = (x < lo) | (x > hi) | ~np.isfinite(x)
    n_range = int(bad.sum())
    if n_range and cfg.press_pad_s > 0:
        bad = maximum_filter1d(bad, size=2 * int(cfg.press_pad_s * fs) + 1, mode='nearest')
    if n_range:
        steps.append(f'{n_range} out-of-range [{lo:g},{hi:g}]')

    mask = bad.copy()
    if cfg.live_mask:
        k = int(cfg.live_block_s * fs)
        nb = len(x) // k
        blk = x[:nb * k].reshape(nb, k).copy()
        blk[bad[:nb * k].reshape(nb, k)] = np.nan
        with quiet():
            pp = np.nanpercentile(blk, 95, 1) - np.nanpercentile(blk, 5, 1)
            med = np.nanmedian(blk, 1)
        min_pp, min_med, max_med = cfg.rules_for(label)
        dead = ~((pp > min_pp) & (med > min_med) & (med < max_med))
        mask[:nb * k] |= np.repeat(dead, k)
        mask[nb * k:] = True                  # ragged tail: no block to judge it by
        secs = dead.sum() * cfg.live_block_s
        steps.append(f'{secs / 60:.0f} min not live' if secs >= 60
                     else f'{secs:.0f} s not live')

    x[mask] = np.nan
    x = bandlimit(x, fs, cfg)
    qc.append(f'  {label:<5} ' + ('; '.join(steps) if steps else 'unmodified')
              + f'  -> {100 * np.isnan(x).mean():5.1f}% voided')
    return x


def clean_ecg(x, fs, label, rail, cfg, qc):
    """NaN out ADC saturation, then subtract an ST-preserving wander estimate."""
    steps = []
    if cfg.sat_mask and np.isfinite(rail):
        sat = np.abs(x) >= rail
        n_sat = int(sat.sum())
        if n_sat and cfg.sat_pad_s > 0:
            sat = maximum_filter1d(sat, size=2 * int(cfg.sat_pad_s * fs) + 1, mode='nearest')
        x[sat] = np.nan
        if n_sat:
            steps.append(f'{n_sat} saturated >= {rail:.3f} mV')

    if cfg.baseline:
        w1 = max(1, int(cfg.baseline_w1_s * fs))
        nb = len(x) // w1
        with quiet():
            m1 = np.nanmedian(x[:nb * w1].reshape(nb, w1), axis=1)
        idx = np.arange(nb)
        good = np.isfinite(m1)
        if good.sum() >= 2:
            m1 = np.interp(idx, idx[good], m1[good])
            size = max(3, int(round(cfg.baseline_w2_s / cfg.baseline_w1_s)) | 1)
            m2 = median_filter(m1, size=size, mode='nearest')
            base = np.interp(np.arange(len(x)), idx * w1 + w1 / 2.0, m2)
            x -= base
            steps.append(f'wander removed ({cfg.baseline_w1_s:g}/{cfg.baseline_w2_s:g} s median)')
        else:
            steps.append('baseline skipped (too few valid blocks)')

    x = bandlimit(x, fs, cfg)
    qc.append(f'  {label:<5} ' + ('; '.join(steps) if steps else 'unmodified')
              + f'  -> {100 * np.isnan(x).mean():5.2f}% voided')
    return x


# ----------------------------------------------------------------- outputs --
def detect_qrs(ecg, fs):
    y = np.nan_to_num(ecg, nan=0.0)
    b, a = butter(3, [8 / (fs / 2), 30 / (fs / 2)], 'band')
    f = filtfilt(b, a, y)
    r, _ = find_peaks(np.abs(f), height=4 * np.median(np.abs(f)), distance=int(0.3 * fs))
    return r[np.isfinite(ecg[np.clip(r, 0, len(ecg) - 1)])]


def per_second(i0, i1, fs, r_peaks, chans, labels, start):
    """One row per whole second in [i0, i1). t_sec stays absolute from file start."""
    sec0, sec1 = i0 // fs, i1 // fs
    secs = max(0, sec1 - sec0)
    out = {'t_sec': np.arange(sec0, sec1, dtype=np.int64)}
    if start is not None:
        out['timestamp'] = pd.to_datetime(start) + pd.to_timedelta(out['t_sec'], 's')

    hr = np.full(secs, np.nan)
    if r_peaks.size > 2 and secs:
        inst = 60.0 / np.clip(np.diff(r_peaks) / fs, 0.25, 3.0)
        which = (r_peaks[1:] // fs).astype(int) - sec0
        ok = (which >= 0) & (which < secs)
        if ok.any():
            s = pd.Series(inst[ok]).groupby(which[ok]).median()
            hr[s.index.values] = s.values
    out['HR_bpm'] = hr

    for lab in labels:
        x = chans[lab][sec0 * fs:sec1 * fs].reshape(secs, fs)
        valid = np.isfinite(x)
        with quiet():
            if lab in ECG_LABELS:
                out[f'{lab}_valid'] = np.round(valid.mean(1), 3)
            else:
                out[f'{lab}_mean'] = np.nanmean(x, 1)
                out[f'{lab}_min'] = np.nanmin(np.where(valid, x, np.nan), 1)
                out[f'{lab}_max'] = np.nanmax(np.where(valid, x, np.nan), 1)
                out[f'{lab}_valid'] = np.round(valid.mean(1), 3)
    return pd.DataFrame(out)


def write_full_csv(path, chans, labels, i0, i1, fs, start, chunk=250_000):
    rows = i1 - i0
    stack = np.empty((rows, len(labels)), dtype=np.float32)
    for j, lab in enumerate(labels):
        stack[:, j] = chans[lab][i0:i1]
    t_ns = None
    if start is not None:
        t_ns = np.int64(pd.Timestamp(start).value) + \
               np.round(np.arange(i0, i1, dtype=np.float64) * 1e9 / fs).astype(np.int64)
    with open(path, 'w', newline='') as fh:
        for i in range(0, rows, chunk):
            j = min(i + chunk, rows)
            d = {}
            if t_ns is not None:
                d['timestamp'] = t_ns[i:j].view('datetime64[ns]')
            d['t_sec'] = np.arange(i0 + i, i0 + j) / fs
            frame = pd.DataFrame(d)
            frame = pd.concat([frame, pd.DataFrame(stack[i:j], columns=list(labels),
                                                   index=frame.index)], axis=1)
            frame.to_csv(fh, index=False, header=(i == 0), float_format='%.4f', na_rep='')
    return path


# --------------------------------------------------------------------- cli --
def build_config(a) -> Config:
    cfg = Config.raw() if a.raw else Config()
    if not a.raw:
        cfg.unwrap = not a.no_unwrap
        cfg.sat_mask = not a.no_sat_mask
        cfg.baseline = not a.no_baseline
        cfg.live_mask = not a.no_live_mask
        cfg.sat_threshold = a.sat_threshold
        cfg.sat_pad_s = a.sat_pad
        cfg.baseline_w1_s = a.baseline_window
        cfg.baseline_w2_s = a.baseline_window * 3
        cfg.press_pad_s = a.press_pad
        for spec in a.press_limit or []:
            try:
                ch, rng = spec.split('=', 1)
                lo, hi = rng.split(':')
                cfg.press_limits[ch] = (float(lo), float(hi))
            except ValueError:
                sys.exit(f'--press-limit expects CH=LO:HI, got {spec!r}')
    cfg.highpass = a.highpass
    cfg.lowpass = a.lowpass
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stem', help='path without extension, e.g. sample/SYNTH01')
    ap.add_argument('--outdir', default=None)
    ap.add_argument('--raw', action='store_true',
                    help='write the signal exactly as recorded, no cleaning at all')
    ap.add_argument('--trend-only', action='store_true', help='skip the ~600 MB full-rate CSV')
    ap.add_argument('--start', type=float, default=None, metavar='SEC',
                    help='trim: first second to export (dead time before the case)')
    ap.add_argument('--stop', type=float, default=None, metavar='SEC',
                    help='trim: last second to export')
    g = ap.add_argument_group('cleaning (ignored with --raw)')
    g.add_argument('--no-unwrap', action='store_true', help='keep the 16-bit pressure overflow')
    g.add_argument('--no-sat-mask', action='store_true', help='keep saturated ECG samples')
    g.add_argument('--sat-threshold', type=float, default=None, help='mV; default auto-detect')
    g.add_argument('--sat-pad', type=float, default=0.012, help='s dropped either side (0.012)')
    g.add_argument('--no-baseline', action='store_true', help='keep ECG baseline wander')
    g.add_argument('--baseline-window', type=float, default=0.200, help='s, stage-1 median (0.2)')
    g.add_argument('--no-live-mask', action='store_true', help='keep transducer-off stretches')
    g.add_argument('--press-pad', type=float, default=0.25, help='s of ringdown dropped (0.25)')
    g.add_argument('--press-limit', action='append', metavar='CH=LO:HI',
                   help='physiologic window, repeatable, e.g. AO=-40:300')
    g.add_argument('--highpass', type=float, default=None, help='Hz (off by default)')
    g.add_argument('--lowpass', type=float, default=None, help='Hz (off by default)')
    a = ap.parse_args()

    cfg = build_config(a)
    stem = Path(a.stem).expanduser().resolve()
    outdir = Path(a.outdir).expanduser().resolve() if a.outdir else stem.parent / 'derived'
    outdir.mkdir(parents=True, exist_ok=True)
    tag = 'raw' if a.raw else 'clean'

    meta, labels, n, c, fs, start = parse_header(stem)
    qc = [f'source      : {stem.name}.bin  ({n * c * 8:,} bytes)',
          f'mode        : {tag.upper()}' + ('   (no cleaning applied)' if a.raw else ''),
          f'settings    : clean_export.py {stem.name} '
          + ('--raw' if a.raw else cfg.as_flags() or '(defaults)'),
          f'channels    : {c}  {labels}',
          f'sample rate : {fs} Hz',
          f'duration    : {n / fs / 3600:.3f} h  ({n:,} samples)']
    if start:
        qc.append(f'start (.inf): {start:%Y-%m-%d %H:%M:%S}')
    if 'Stop Time' in meta and start:
        try:
            stop = datetime.strptime(meta['Stop Time'].strip(), '%m/%d/%Y %I:%M:%S %p')
            span = (stop - start).total_seconds()
            qc.append(f'HEADER SPAN vs SAMPLES: {span:,.0f} s vs {n / fs:,.0f} s '
                      f'-> {span - n / fs:+,.0f} s unexplained. Wall-clock alignment is NOT '
                      f'verified; trust t_sec, not timestamp.')
        except ValueError:
            pass

    mm = np.memmap(stem.with_suffix('.bin'), dtype='<f8', mode='r', shape=(n, c))

    rail = np.inf
    ecg_idx = [i for i, l in enumerate(labels) if l in ECG_LABELS]
    if cfg.sat_mask and ecg_idx:
        if cfg.sat_threshold is not None:
            rail = cfg.sat_threshold
            qc.append(f'ECG saturation threshold {rail:.3f} mV (given)')
        else:
            amax = max(float(np.abs(mm[::13, i]).max()) for i in ecg_idx)
            hits = sum(int((np.abs(mm[::13, i]) >= amax * RAIL_FRAC).sum()) for i in ecg_idx)
            if hits > 100:
                rail = amax * RAIL_FRAC
                qc.append(f'ECG full scale {amax:.3f} mV -> saturation threshold {rail:.3f} mV')
            else:
                qc.append('no ECG saturation detected')

    qc.append('\n--- per channel ---')
    chans = {}
    for i, lab in enumerate(labels):
        x = np.array(mm[:, i], dtype=np.float64)
        if a.raw and not (cfg.highpass or cfg.lowpass):
            qc.append(f'  {lab:<5} unmodified  ->  0.00% voided')
        elif lab in ECG_LABELS:
            x = clean_ecg(x, fs, lab, rail, cfg, qc)
        else:
            x = clean_pressure(x, fs, lab, cfg, qc)
        chans[lab] = x
        print(qc[-1], flush=True)

    lead = next((l for l in ('II', 'I', 'V5') if l in chans), None)
    r = detect_qrs(chans[lead], fs) if lead else np.array([], dtype=int)
    qc.append(f'\nQRS on lead {lead}: {r.size:,} beats '
              f'({60 * r.size / (n / fs):.0f} bpm mean over the file)')

    # trimming happens at write time, so cleaning still sees the whole recording for
    # baseline and live-block context; t_sec stays absolute from file start
    i0 = 0 if a.start is None else clamp_idx(a.start * fs, n)
    i1 = n if a.stop is None else clamp_idx(a.stop * fs, n)
    if i1 <= i0:
        sys.exit(f'--start {a.start} / --stop {a.stop} select an empty range')
    if (i0, i1) != (0, n):
        qc.append(f'\ntrimmed to {i0 / fs:,.1f}-{i1 / fs:,.1f} s '
                  f'({(i1 - i0) / fs / 60:.1f} min of {n / fs / 60:.1f}); t_sec stays absolute')
        print(qc[-1], flush=True)

    trend = per_second(i0, i1, fs, r, chans, labels, start)
    tpath = outdir / f'{stem.name}_{tag}_trend.csv'
    trend.to_csv(tpath, index=False, float_format='%.2f', na_rep='')
    qc.append(f'wrote {tpath.name}  ({len(trend):,} rows x {trend.shape[1]} cols)')
    print(qc[-1], flush=True)

    if not a.trend_only:
        fpath = outdir / f'{stem.name}_{tag}.csv'
        print(f'writing {fpath.name} ...', flush=True)
        write_full_csv(fpath, chans, labels, i0, i1, fs, start)
        qc.append(f'wrote {fpath.name}  ({i1 - i0:,} rows x {len(labels) + 2} cols, '
                  f'{fpath.stat().st_size / 1e6:,.0f} MB)')
        print(qc[-1], flush=True)

    qpath = outdir / f'{stem.name}_{tag}_qc.txt'
    qpath.write_text('\n'.join(qc) + '\n')
    print(f'wrote {qpath.name}')


if __name__ == '__main__':
    main()
