#!/usr/bin/env python3
"""
Run every suite against the synthetic sample.

    pip install -r requirements.txt playwright && python -m playwright install chromium
    python tests/run_all.py

Each suite is also runnable on its own and prints one line per assertion. All of them use
sample/SYNTH01 only -- no patient data is touched, so these are safe to run anywhere and
safe to have in a public repository.

The suites that exercise real recordings (clock anchoring, the QRS detector against charted
HR, the plausibility check) cannot live here: they need the gitignored Data/ folder. Keep
those local.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = [
    ('test_viewer.py', 'case log: parsing, panel, timeline, event CSV'),
    ('test_log_ui.py', 'SpO2 colour, folder opening, resizable track and text'),
    ('test_cursor.py', 'time cursor: instant, value, pin, clear'),
    ('test_csv_parity.py', 'viewer CSV vs clean_export CSV, column by column'),
]


def main():
    if not (ROOT / 'sample/SYNTH01.bin').exists():
        sys.exit('sample/SYNTH01.bin missing — run scripts/make_sample.py first')
    if not (ROOT / 'sample/SYNTH01.docx').exists():
        sys.exit('sample/SYNTH01.docx missing — run scripts/make_sample_log.py first')

    failed = []
    for name, what in SUITES:
        print(f'\n{"=" * 72}\n{name}  —  {what}\n{"=" * 72}', flush=True)
        r = subprocess.run([sys.executable, str(ROOT / 'tests' / name)], cwd=ROOT)
        if r.returncode:
            failed.append(name)

    print(f'\n{"=" * 72}')
    print(f'{len(SUITES) - len(failed)} of {len(SUITES)} suites passed')
    for f in failed:
        print(f'  FAILED  {f}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
