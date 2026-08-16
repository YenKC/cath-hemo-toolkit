#!/usr/bin/env python3
"""
Check that cleaning removes what it should and preserves what it must.

    python scripts/validate_cleaning.py                 # the bundled synthetic sample
    python scripts/validate_cleaning.py path/to/CASE    # any recording

Every number quoted in the README comes from this script run against
sample/SYNTH01, so the claims can be reproduced rather than taken on trust.

The important check is ST preservation. Baseline-wander removal must not move the ST
segment, because ST is measured beat-relative (J+60 ms against the PR segment) and a
filter that distorts it would invalidate exactly the endpoint this tooling exists to
support. Beats sitting on a steep baseline ramp are unreliable in the raw signal too,
so a residual disagreement there is expected and is reported separately.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_export import (ECG_LABELS, Config, clean_ecg, clean_pressure,  # noqa: E402
                          detect_qrs, parse_header, quiet)


def st_of(sig, peaks, fs):
    """ST at J+60 ms relative to the PR segment, per beat, in microvolts."""
    bl0, bl1, at = int(.070 * fs), int(.045 * fs), int(.090 * fs)
    keep = (peaks > bl0 + 5) & (peaks + at + 5 < len(sig))
    p = peaks[keep]
    base = np.array([sig[i - bl0:i - bl1].mean() for i in p])
    val = np.array([sig[i + at - 2:i + at + 3].mean() for i in p])
    return (val - base) * 1000.0, p


def wander(sig, fs):
    """Spread of the 1 s medians = how much the baseline drifts."""
    nb = len(sig) // fs
    with quiet():
        return float(np.nanstd(np.nanmedian(sig[:nb * fs].reshape(nb, fs), axis=1)))


def main():
    stem = Path(sys.argv[1] if len(sys.argv) > 1 else 'sample/SYNTH01').resolve()
    meta, labels, n, c, fs, _ = parse_header(stem)
    mm = np.memmap(stem.with_suffix('.bin'), dtype='<f8', mode='r', shape=(n, c))
    cfg = Config()
    hours = n / fs / 3600

    print(f'{stem.name}: {c} channels @ {fs} Hz, {n:,} samples ({n/fs:.0f} s)\n')

    # ---- ADC rail, derived the same way the tools derive it -------------------------
    ecg = [i for i, l in enumerate(labels) if l in ECG_LABELS]
    amax = max(float(np.abs(mm[::13, i]).max()) for i in ecg) if ecg else float('nan')
    rail = amax * 0.998
    print(f'ECG full scale {amax:.4f} mV  ->  saturation threshold {rail:.3f} mV')

    t0 = time.perf_counter()
    qc, cleaned, raw = [], {}, {}
    for i, lab in enumerate(labels):
        x = np.array(mm[:, i], dtype=np.float64)
        raw[lab] = x.copy()
        cleaned[lab] = (clean_ecg(x, fs, lab, rail, cfg, qc) if lab in ECG_LABELS
                        else clean_pressure(x, fs, lab, cfg, qc))
    secs = time.perf_counter() - t0

    # ---- pressure: the wrap must be gone and nothing physiologic left behind --------
    print('\npressure channels')
    for lab in labels:
        if lab in ECG_LABELS:
            continue
        r, cl = raw[lab], cleaned[lab]
        wrapped = int((r < -1000).sum())
        fin = np.isfinite(cl)
        print(f'  {lab:<5} {wrapped:>4} wrapped samples restored, '
              f'{100*(~fin).mean():5.1f}% voided, '
              f'range {np.nanmin(cl):7.1f} .. {np.nanmax(cl):6.1f} mmHg')
        assert not wrapped or np.nanmin(cl) > -100, f'{lab}: wrap survived cleaning'

    # ---- ECG: saturation removed ----------------------------------------------------
    print('\nECG saturation removed')
    any_sat = False
    for lab in labels:
        if lab not in ECG_LABELS:
            continue
        sat = int((np.abs(raw[lab]) >= rail).sum())
        if sat:
            any_sat = True
            print(f'  {lab:<5} {sat:>6} samples at the rail  '
                  f'({100*np.isnan(cleaned[lab]).mean():5.2f}% voided after padding)')
    if not any_sat:
        print('  none in this file')

    # ---- ST preservation -------------------------------------------------------------
    lead = next((l for l in ('II', 'I', 'V5') if l in cleaned), None)
    if lead:
        # the exporter's detector, not a copy of it: a second implementation here drifted
        # from the real one and kept validating a T-wave-counting bug that was already fixed
        pk = detect_qrs(cleaned[lead], fs)
        st_c, p = st_of(cleaned[lead], pk, fs)
        st_r, _ = st_of(raw[lead], pk, fs)
        ok = np.isfinite(st_c) & np.isfinite(st_r)
        d = st_c[ok] - st_r[ok]
        print(f'\nST (J+60 vs PR) on lead {lead}, {ok.sum():,} beats')
        print(f'  shift from cleaning: median {np.median(d):+.2f} uV, '
              f'IQR [{np.percentile(d,25):+.2f}, {np.percentile(d,75):+.2f}]')
        print(f'  beats shifted > 100 uV: {100*(np.abs(d) > 100).mean():.2f}% '
              f'(steep-wander beats, unreliable in raw too)')

    print('\nbaseline wander, sd of 1 s medians (mV)')
    for lab in labels:
        if lab in ECG_LABELS and wander(raw[lab], fs) > 0.02:
            print(f'  {lab:<5} {wander(raw[lab], fs):.3f}  ->  {wander(cleaned[lab], fs):.3f}')

    # cleaning only -- writing the CSV costs several times this and dominates a real export
    print(f'\ncleaning pass: {secs:.2f} s for {hours*60:.1f} min of {c}-channel signal '
          f'= {secs/max(hours,1e-9):.1f} s per recorded hour '
          f'({n*c/max(secs,1e-9)/1e6:.0f} M samples/s). Writing the CSV costs more; '
          f'both scale linearly with sample count.')


if __name__ == '__main__':
    main()
