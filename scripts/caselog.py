#!/usr/bin/env python3
"""
Read a Mac-Lab case log and put its events on the recording's time base.

    python scripts/caselog.py sample/SYNTH01.docx --inf sample/SYNTH01.inf

Used by clean_export.py to fold the log into the exported CSVs, and runnable on its own to
see what a log parses to before committing to an export.

The .bin has no annotation stream, so the log document is the only record of when a balloon
went up. This module turns it into columns a statistics package can group by, the important
one being `peri_t`: signed seconds to the nearest inflation. Aligning every inflation on
peri_t == 0 is what makes "does the vital sign move around balloon inflation" a question you
can average over instead of eyeball case by case.

It is a deliberate second implementation of the parser in viewer/cath_viewer.html -- the two
tools share the *definition*, not the code, exactly as they already do for cleaning. Change
the rules here and in the viewer's EV_KINDS together.

Layout expected, which is what the Mac-Lab export produces:
    a line holding only a time      1:39:40 PM
    the event summary               Balloon inflated for 7 sec @ 10 atm in the LM.
    zero or more comment lines      fix 24
Everything before the first timestamp is the patient-information block and is not exported.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ reading --
T_LINE = re.compile(r'^(\d{1,2}):(\d{2}):(\d{2})(?:\s*([AP])\.?\s*M\.?)?$', re.I)
PLAIN_EXT = {'.txt', '.log', '.csv'}


def _norm(s: str) -> str:
    return re.sub(r'[\s ]+', ' ', s).strip()


def xml_lines(xml: str) -> list[str]:
    """One line per paragraph. Entities are decoded only after tags are stripped, so an
    escaped &lt; in the text can never be mistaken for markup."""
    xml = re.sub(r'<(?:w:br|w:cr|text:line-break)\b[^>]*>', '\n', xml)
    xml = re.sub(r'<(?:w:tab|text:tab|text:s)\b[^>]*>', ' ', xml)
    xml = re.sub(r'</(?:w:p|text:p|text:h)>', '\n', xml)
    xml = re.sub(r'<[^>]*>', '', xml)
    return [_norm(unescape(line)) for line in xml.split('\n')]


def read_lines(path) -> list[str]:
    p = Path(path)
    if p.suffix.lower() in PLAIN_EXT:
        return [_norm(l) for l in p.read_text(encoding='utf-8', errors='replace').splitlines()]
    if p.suffix.lower() == '.xml':
        return xml_lines(p.read_text(encoding='utf-8', errors='replace'))
    if not zipfile.is_zipfile(p):
        raise ValueError(f'{p.name}: not a .docx/.odt (no zip container) and not a .txt')
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        inner = ('word/document.xml' if 'word/document.xml' in names
                 else 'content.xml' if 'content.xml' in names else None)
        if inner is None:
            raise ValueError(f'{p.name}: no word/document.xml or content.xml inside')
        return xml_lines(z.read(inner).decode('utf-8', 'replace'))


# ------------------------------------------------------------- classifying --
# First match wins, so this is the priority order. Keep in step with EV_KINDS in the viewer.
KINDS = [
    ('inflation', re.compile(r'\binflated\s+for\b|\bdeployed\s+for\b'
                             r'|\b(?:balloon|stent)\b[^.]{0,40}\b(?:inflat|deploy)', re.I)),
    ('procedure', re.compile(r'^procedure\s*:', re.I)),
    ('pressure', re.compile(r"^[A-Za-z][\w']{0,7}\s*:\s*-?\d+\s*/\s*-?\d+|^snapshot\b", re.I)),
    ('vitals', re.compile(r'\bSpO2\b|\bNBP\b|\bHR\s*\d+\s*bpm\b', re.I)),
    ('lab', re.compile(r'\bACT\b|^SAT\s*:|\bcontrast\b', re.I)),
    ('med', re.compile(r'\b(?:heparin|nitro\w*|NTG|adenosine?|atropine|dopamine|dobutamine'
                       r'|epinephrine?|norepinephrine?|verapamil|lidocaine|amiodarone|morphine'
                       r'|fentanyl|midazolam|aspirin|ticagrelor|clopidogrel)\b'
                       r'|\b\d[\d,.]*\s*(?:units|mcg|mg|ml)\b', re.I)),
    ('device', re.compile(r'\bthrombect\w*|aspirat\w*|rotablat\w*|IVUS|OCT\b|FFR|iFR'
                          r'|guide\s?wire|guiding|catheter|sheath|pacemaker|IABP|pullback', re.I)),
    # supply-catalogue lines: "NC Trek 4.0mm x 12mm 143cm As:Abbott 1012453-12"
    ('hardware', re.compile(r'\bAs:\s*\S|\b\d+\s*Fr\b|\b\d+(?:\.\d+)?\s*mm\s*[x×]\s*\d+'
                            r'|\b\d+\s*cm\b|\b0?\.\d+"\s*[x×]', re.I)),
]

RE_DUR = re.compile(r'\bfor\s+(\d+(?:\.\d+)?)\s*(?:sec\w*|s)\b', re.I)
RE_ATM = re.compile(r'@\s*(\d+(?:\.\d+)?)\s*atm', re.I)
RE_TGT = re.compile(r'\b(?:in|on|at)\s+the\s+(.+?)\s*\.?\s*$', re.I)
RE_HR = re.compile(r'\bHR\s*[:=]?\s*(\d+)', re.I)
RE_PRESS = re.compile(r'(-?\d+)\s*/\s*(-?\d+)\s*/\s*(-?\d+)')
RE_CHAN = re.compile(r"^(?:snapshot\s*:\s*)?([A-Za-z][\w']{0,7})\s*:", re.I)
RE_SPO2 = re.compile(r'SpO2\s*:?\s*(\d+)\s*%', re.I)
RE_NBP = re.compile(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*NBP', re.I)
RE_RR = re.compile(r'\bRR\s*:?\s*(\d+)\s*/?\s*min', re.I)


@dataclass
class Event:
    sod: float                       # seconds of day, past 86400 if the case crossed midnight
    text: str
    notes: list = field(default_factory=list)
    kind: str = 'other'
    dur: float | None = None
    atm: float | None = None
    target: str | None = None
    hr: int | None = None
    chan: str | None = None
    sys: int | None = None
    dia: int | None = None
    mean: int | None = None
    spo2: int | None = None
    rr: int | None = None
    nbp: tuple | None = None
    t: float = float('nan')          # seconds from the start of the recording, set by align()

    @property
    def has_vitals(self) -> bool:
        return self.spo2 is not None or self.nbp is not None or self.rr is not None \
            or (self.kind == 'vitals' and self.hr is not None)


def classify(text: str) -> str:
    for name, rx in KINDS:
        if rx.search(text):
            return name
    return 'other'


def _enrich(e: Event) -> Event:
    t = e.text
    m = RE_DUR.search(t)
    if m:
        e.dur = float(m.group(1))
    m = RE_ATM.search(t)
    if m:
        e.atm = float(m.group(1))
    m = RE_TGT.search(t)
    if m:
        e.target = m.group(1)
    m = RE_HR.search(t)
    if m:
        e.hr = int(m.group(1))
    if e.kind == 'pressure':
        m = RE_PRESS.search(t)
        if m:
            e.sys, e.dia, e.mean = int(m.group(1)), int(m.group(2)), int(m.group(3))
        m = RE_CHAN.match(t)
        if m:
            e.chan = m.group(1).upper()
    if e.kind == 'vitals':
        m = RE_SPO2.search(t)
        if m:
            e.spo2 = int(m.group(1))
        m = RE_NBP.search(t)
        if m:
            e.nbp = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = RE_RR.search(t)
        if m:
            e.rr = int(m.group(1))
    return e


def _sod(m: re.Match) -> int:
    h = int(m.group(1))
    ap = (m.group(4) or '').upper()
    if ap == 'P' and h != 12:
        h += 12
    if ap == 'A' and h == 12:
        h = 0
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3))


@dataclass
class CaseLog:
    events: list
    head: list
    info: dict
    source: str = ''

    def __len__(self):
        return len(self.events)

    @property
    def span(self) -> float:
        return (self.events[-1].sod - self.events[0].sod) if self.events else 0.0

    def counts(self) -> dict:
        out = {}
        for e in self.events:
            out[e.kind] = out.get(e.kind, 0) + 1
        return out


def parse(lines) -> CaseLog:
    events, head, cur = [], [], None
    prev, day = -1.0, 0
    for raw in lines:
        s = (raw or '').strip()
        if not s:
            continue
        m = T_LINE.match(s)
        if m:
            if cur is not None and cur.text:
                events.append(_enrich(cur))
            sod = _sod(m) + day * 86400
            if prev >= 0 and sod < prev - 3600:      # the case ran past midnight
                day += 1
                sod += 86400
            prev = sod
            cur = Event(sod=sod, text='')
            continue
        if cur is None:
            head.append(s)
            continue
        if not cur.text:
            cur.text = s
            cur.kind = classify(s)
        else:
            cur.notes.append(s)
    if cur is not None and cur.text:
        events.append(_enrich(cur))

    info = {}
    for h in head:
        m = re.match(r'^MRN\s*(\S+)', h, re.I)
        if m:
            info['mrn'] = m.group(1)
        m = re.match(r'^Study\s*Date\s*(\d{1,2}/\d{1,2}/\d{2,4})', h, re.I)
        if m:
            info['date'] = m.group(1)
    return CaseLog(events=events, head=head, info=info)


def load(path) -> CaseLog:
    log = parse(read_lines(path))
    log.source = Path(path).name
    return log


# -------------------------------------------------------------- alignment --
def anchor_sod(log: CaseLog, mode: str, start) -> float:
    """Seconds-of-day that t_sec == 0 corresponds to."""
    if not log.events:
        return 0.0
    if mode == 'first' or start is None:
        return log.events[0].sod
    return start.hour * 3600 + start.minute * 60 + start.second


def score(log: CaseLog, mode: str, start, dur: float, offset: float = 0.0) -> float:
    """Fraction of events that land on the recording under this anchoring. This is what
    catches a header clock that disagrees with its own case log."""
    if not log.events:
        return 0.0
    a = anchor_sod(log, mode, start)
    inside = sum(1 for e in log.events if -120 <= e.sod - a + offset <= dur + 120)
    return inside / len(log.events)


def choose_anchor(log: CaseLog, start, dur: float, offset: float = 0.0):
    sh = score(log, 'header', start, dur, offset)
    sf = score(log, 'first', start, dur, offset)
    return ('header' if sh >= sf - 1e-9 else 'first'), sh, sf


def align(log: CaseLog, mode: str, start, offset: float = 0.0) -> None:
    a = anchor_sod(log, mode, start)
    for e in log.events:
        e.t = e.sod - a + offset


def hr_marks(log: CaseLog):
    """(t, HR) pairs the log records. The nurse charts HR and the ECG measures it, so this
    is one quantity captured twice by two independent clocks -- which makes it the thing to
    align on when the wall clocks disagree."""
    return [(e.t, float(e.hr)) for e in log.events if e.hr is not None]


def fit_offset(marks, hr_series, lo=-900.0, hi=900.0, step=1.0, min_pts=5):
    """Slide the log against the measured per-second HR and find the shift that lines them up.

    hr_series is HR indexed by whole second from the start of the recording, NaN where no
    beat was detected. Returns the best offset plus enough context to judge whether to
    believe it: `chance` is the median error over the whole scan, and `plateau` is how wide
    the near-minimum region is. A minimum barely better than chance, or one sitting on a
    plateau hundreds of seconds wide, is not an alignment -- it is a coincidence.
    """
    out = {'ok': False, 'reason': '', 'best': 0.0, 'mae': float('nan'),
           'chance': float('nan'), 'n': 0, 'plateau': float('nan'), 'at_zero': float('nan')}
    if len(marks) < min_pts:
        out['reason'] = f'only {len(marks)} HR marks in the log; need {min_pts}'
        return out
    hr = np.asarray(hr_series, dtype=float)
    if not np.isfinite(hr).any():
        out['reason'] = 'no HR could be measured from the ECG'
        return out

    mt = np.array([m[0] for m in marks], dtype=float)
    mv = np.array([m[1] for m in marks], dtype=float)
    offs = np.arange(lo, hi + step / 2, step)
    mae = np.full(offs.size, np.nan)
    cnt = np.zeros(offs.size, dtype=int)
    for k, d in enumerate(offs):
        idx = np.rint(mt + d).astype(np.int64)
        ok = (idx >= 0) & (idx < hr.size)
        if ok.sum() < min_pts:
            continue
        meas = hr[idx[ok]]
        good = np.isfinite(meas)
        if good.sum() < min_pts:
            continue
        mae[k] = float(np.median(np.abs(mv[ok][good] - meas[good])))
        cnt[k] = int(good.sum())
    if not np.isfinite(mae).any():
        out['reason'] = 'the log never overlaps the measured HR at any offset in range'
        return out

    k = int(np.nanargmin(mae))
    best, bmae = float(offs[k]), float(mae[k])
    chance = float(np.nanmedian(mae))
    near = np.isfinite(mae) & (mae <= bmae + 1.0)          # within 1 bpm of the minimum
    plateau = float(offs[near].max() - offs[near].min()) if near.any() else float('nan')
    z = int(np.argmin(np.abs(offs)))
    out.update(best=best, mae=bmae, chance=chance, n=int(cnt[k]), plateau=plateau,
               at_zero=float(mae[z]) if np.isfinite(mae[z]) else float('nan'))
    if bmae > 0.75 * chance:
        out['reason'] = (f'best error {bmae:.1f} bpm is no better than the {chance:.1f} bpm '
                         f'an arbitrary offset gives, so there is no match to find')
    elif plateau > 120:
        out['reason'] = (f'HR moves too little over this case to locate the log: every offset '
                         f'across a {plateau:.0f} s span fits within 1 bpm of the best one. '
                         f'Alignment has to come from a clock, not from the signal')
    else:
        out['ok'] = True
    return out


ACCESS_RE = re.compile(r'punctur|sheath insert|access|was entered|cannulat', re.I)


def access_events(log: CaseLog):
    """Logged moments an arterial line could first exist. A pressure trace cannot predate
    the puncture that produced it, which makes this the one alignment check physics can
    settle rather than a clock."""
    return [e for e in log.events if ACCESS_RE.search(e.text)]


def plausibility(log: CaseLog, first_live_s, lag_s: float = 131.0):
    """Compare when the arterial trace actually starts against when access was logged.

    Returns (verdict, message). `lag_s` is how long after puncture the transducer came
    live on the one case whose clock is independently verified -- puncture to sheath to
    catheter to zeroed transducer -- so it is an observed figure, not a guess.
    """
    acc = access_events(log)
    if first_live_s is None or not acc:
        return 'unknown', 'no arterial trace or no logged access event to compare'
    t_acc = min(e.t for e in acc)
    slack = first_live_s - t_acc
    if slack >= -60:
        return 'ok', (f'arterial trace starts {slack:+.0f} s relative to the first logged '
                      f'access, which is consistent')
    need = -slack + lag_s
    return 'impossible', (
        f'the arterial trace is live at {first_live_s:.0f} s but access is not logged until '
        f'{t_acc:.0f} s — a pressure waveform {-slack:.0f} s before the artery was punctured. '
        f'The anchor is wrong by at least {-slack:.0f} s. Matching the {lag_s:.0f} s '
        f'puncture-to-live delay seen on a clock-verified case puts the correction near '
        f'--log-offset {-need:.0f}. Treat that as an estimate: it assumes no arterial line '
        f'was already in place from before the case')


def alignment_note(log: CaseLog, dur: float) -> str:
    """What the overlap of log and recording implies about the offset, when fitting fails.

    Neither signal both sources record can pin the log down here: HR is charted often but
    barely moves, and AO moves plenty but is charted twice. So the honest statement is a
    bound from the two spans, not a number.
    """
    if not log.events:
        return ''
    over = log.span - dur
    if over <= 0:
        return (f'The log ({log.span / 60:.0f} min) fits inside the recording '
                f'({dur / 60:.0f} min), so the offset lies somewhere in a '
                f'{-over / 60:.0f} min window and cannot be narrowed further from the data.')
    return (f'The log spans {log.span / 60:.0f} min but the recording is {dur / 60:.0f} min, '
            f'so they cannot both be right at every point: at least {over / 60:.0f} min of '
            f'events fall outside the samples whatever the offset. Residual alignment '
            f'uncertainty is of that order.')


# ----------------------------------------------------------------- columns --
EVENT_COLUMNS = ['event', 'event_kind', 'infl', 'infl_n', 'infl_target', 'infl_atm',
                 'infl_t', 'peri_n', 'peri_t', 'log_hr', 'log_spo2', 'log_rr',
                 'log_nbp_sys', 'log_nbp_dia', 'log_nbp_mean', 'log_age_s']


def event_columns(log: CaseLog, t_sec, peri_window: float = 120.0) -> dict:
    """Build the per-row event columns for a (sorted, increasing) t_sec array.

    Point events attach to the row that contains them. Inflations are an interval, so every
    row inside one is flagged -- that is the difference between "a balloon went up at 52 s"
    and "these 18 seconds of signal were recorded with the artery occluded". peri_t is
    signed seconds to the nearest inflation start, the column to group by.
    """
    t = np.asarray(t_sec, dtype=np.float64)
    n = t.size
    out = {
        'event': np.full(n, '', dtype=object),
        'event_kind': np.full(n, '', dtype=object),
        'infl': np.zeros(n, dtype=np.int8),
        'infl_n': np.full(n, np.nan),
        'infl_target': np.full(n, '', dtype=object),
        'infl_atm': np.full(n, np.nan),
        'infl_t': np.full(n, np.nan),
        'peri_n': np.full(n, np.nan),
        'peri_t': np.full(n, np.nan),
    }
    if n == 0:
        for c in EVENT_COLUMNS:
            out.setdefault(c, np.full(0, np.nan))
        return out

    # point events -> the row at or before them
    if log.events:
        pos = np.searchsorted(t, [e.t for e in log.events], side='right') - 1
        for e, i in zip(log.events, pos):
            if 0 <= i < n:
                out['event'][i] = f"{out['event'][i]} | {e.text}" if out['event'][i] else e.text
                out['event_kind'][i] = (f"{out['event_kind'][i]}|{e.kind}"
                                        if out['event_kind'][i] else e.kind)

    infls = [e for e in log.events if e.kind == 'inflation']
    for k, e in enumerate(infls, 1):
        a = e.t
        b = a + (e.dur if e.dur else 0.0)
        lo = int(np.searchsorted(t, a, side='left'))
        hi = int(np.searchsorted(t, b, side='left'))
        if hi <= lo:                       # shorter than one row: still mark the row it lands in
            hi = lo + 1
        lo, hi = max(0, lo), min(n, hi)
        if hi <= lo:
            continue
        sl = slice(lo, hi)
        out['infl'][sl] = 1
        out['infl_n'][sl] = k
        out['infl_t'][sl] = t[sl] - a
        out['infl_target'][sl] = e.target or ''
        if e.atm is not None:
            out['infl_atm'][sl] = e.atm

    if infls:
        starts = np.array([e.t for e in infls], dtype=np.float64)
        order = np.argsort(starts, kind='stable')
        s_sorted = starts[order]
        j = np.searchsorted(s_sorted, t)
        left = np.clip(j - 1, 0, s_sorted.size - 1)
        right = np.clip(j, 0, s_sorted.size - 1)
        pick = np.where(np.abs(t - s_sorted[left]) <= np.abs(t - s_sorted[right]), left, right)
        peri_t = t - s_sorted[pick]
        peri_n = (order[pick] + 1).astype(np.float64)
        far = np.abs(peri_t) > peri_window
        peri_t = np.where(far, np.nan, peri_t)
        peri_n = np.where(far, np.nan, peri_n)
        out['peri_t'], out['peri_n'] = peri_t, peri_n

    # charted vitals, carried forward from the last reading (never interpolated)
    vit = [e for e in log.events if e.has_vitals]
    for c in ('log_hr', 'log_spo2', 'log_rr', 'log_nbp_sys', 'log_nbp_dia',
              'log_nbp_mean', 'log_age_s'):
        out[c] = np.full(n, np.nan)
    if vit:
        vt = np.array([e.t for e in vit], dtype=np.float64)
        cols = {
            'log_hr': [e.hr for e in vit],
            'log_spo2': [e.spo2 for e in vit],
            'log_rr': [e.rr for e in vit],
            'log_nbp_sys': [e.nbp[0] if e.nbp else None for e in vit],
            'log_nbp_dia': [e.nbp[1] if e.nbp else None for e in vit],
            'log_nbp_mean': [e.nbp[2] if e.nbp else None for e in vit],
        }
        j = np.searchsorted(vt, t, side='right') - 1
        ok = j >= 0
        jc = np.clip(j, 0, vt.size - 1)
        for name, vals in cols.items():
            arr = np.array([np.nan if v is None else float(v) for v in vals])
            out[name] = np.where(ok, arr[jc], np.nan)
        out['log_age_s'] = np.where(ok, t - vt[jc], np.nan)
    return out


def events_frame(log: CaseLog) -> pd.DataFrame:
    """The standalone event table: one row per event, for joining on t_sec."""
    rows = []
    for e in log.events:
        rows.append({
            't_sec': round(e.t, 3) if np.isfinite(e.t) else None,
            'log_clock': _clock(e.sod),
            'kind': e.kind,
            'dur_s': e.dur,
            'atm': e.atm,
            'target': e.target,
            'channel': e.chan,
            'sys': e.sys, 'dia': e.dia, 'mean': e.mean,
            'hr': e.hr, 'spo2': e.spo2, 'rr': e.rr,
            'nbp_sys': e.nbp[0] if e.nbp else None,
            'nbp_dia': e.nbp[1] if e.nbp else None,
            'nbp_mean': e.nbp[2] if e.nbp else None,
            'text': e.text,
            'notes': ' | '.join(e.notes),
        })
    return pd.DataFrame(rows)


def _clock(sod: float) -> str:
    s = int(sod) % 86400
    h, m, sec = s // 3600, (s // 60) % 60, s % 60
    ap = 'AM' if h < 12 else 'PM'
    return f'{(h % 12) or 12}:{m:02d}:{sec:02d} {ap}'


# --------------------------------------------------------------------- cli --
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('log', help='the case log: .docx, .odt or .txt')
    ap.add_argument('--inf', default=None,
                    help='the matching .inf, so events can be placed on the recording clock')
    ap.add_argument('--csv', default=None, help='write the event table here')
    a = ap.parse_args()

    log = load(a.log)
    if not log.events:
        sys.exit('No timestamped events found. The reader expects a line holding only a '
                 'time, followed by the event text.')

    start, dur = None, float('inf')
    if a.inf:
        from clean_export import parse_header
        _meta, _labels, n, _c, fs, start = parse_header(Path(a.inf).with_suffix(''))
        dur = n / fs
        mode, sh, sf = choose_anchor(log, start, dur)
        align(log, mode, start)
        print(f'anchor      : {mode}   (header scores {sh:.0%}, first-event {sf:.0%})')
        if mode == 'first':
            print('  WARNING: the .inf Start Time disagrees with this log. Sample index is '
                  'the only trustworthy time base for this case.')
    else:
        align(log, 'first', None)
        print('anchor      : first log event = 0 s   (no --inf given)')

    print(f'source      : {log.source}')
    print(f'events      : {len(log)} spanning {log.span / 60:.1f} min')
    print(f'kinds       : {log.counts()}')
    infl = [e for e in log.events if e.kind == 'inflation']
    full = sum(1 for e in infl if e.dur is not None and e.atm is not None and e.target)
    print(f'inflations  : {len(infl)}, {full} with duration + atm + target')
    if infl:
        tg = sorted({e.target for e in infl if e.target})
        print(f'targets     : {tg}')
    if a.csv:
        df = events_frame(log)
        df.to_csv(a.csv, index=False)
        print(f'wrote {a.csv}  ({len(df)} rows x {df.shape[1]} cols)')


if __name__ == '__main__':
    main()
