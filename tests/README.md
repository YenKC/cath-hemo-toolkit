# Tests

```bash
pip install -r requirements.txt playwright
python -m playwright install chromium
python tests/run_all.py
```

Everything here runs against `sample/SYNTH01` only. No patient data is touched, which is
why these can live in a public repository — and why `scripts/make_sample_log.py` exists at
all, so the case-log features have something to be tested against.

| suite | what it protects |
|---|---|
| `test_viewer.py` | case-log parsing, the log panel, events on the timeline, the event CSV |
| `test_log_ui.py` | SpO2 readout colour, folder/multi-case opening, resizable track and text |
| `test_cursor.py` | the time cursor reports the instant it points at, and the value there |
| `test_csv_parity.py` | **the viewer's CSV and `clean_export.py`'s agree column for column** |

## Why the parity suite matters most

`viewer/cath_viewer.html` and `scripts/caselog.py` are two independent implementations of
one specification — JavaScript in the browser, Python in batch — exactly as the cleaning
settings already were. That is a deliberate choice, but it only holds if something checks
it. `test_csv_parity.py` exports the same case both ways and compares all 16 event columns
row by row. It has already caught a real divergence: the viewer wrote time deltas at two
decimal places against Python's four, which quantised every sub-second offset to zero at
240 Hz.

**Change one implementation, run this, change the other.**

## What is deliberately not here

The suites that exercise real recordings — clock anchoring against a case log, the QRS
detector against nurse-charted HR, the arterial-trace-before-puncture check — need the
gitignored `Data/` folder and cannot be committed. Keep those local. They are the ones that
found the substantive bugs, because the synthetic sample has uniform beats and a clock that
agrees with itself; it cannot expose a detector counting T waves or a header five hours out
from its own log.

A green run here means nothing regressed. It does not mean the tool is right on real data.
