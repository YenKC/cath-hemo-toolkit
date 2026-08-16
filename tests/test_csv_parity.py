"""The viewer and clean_export.py are separate implementations of one spec.
This checks their event columns come out byte-identical on the same case."""
import sys, pathlib, subprocess
import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                   ROOT / 'tests/_out') / 'parity'; OUT.mkdir(parents=True, exist_ok=True)
PY = sys.executable
EV = ['event','event_kind','infl','infl_n','infl_target','infl_atm','infl_t',
      'peri_n','peri_t','log_hr','log_spo2','log_rr',
      'log_nbp_sys','log_nbp_dia','log_nbp_mean','log_age_s']
fails, errs = [], []

def check(n, c, d=''):
    print(f'  {"ok  " if c else "FAIL"} {n}' + (f'   {d}' if not c else ''))
    if not c: fails.append(f'{n} :: {d}')

print('== python export ==')
r = subprocess.run([PY, 'scripts/clean_export.py', 'sample/SYNTH01',
                    '--log', 'sample/SYNTH01.docx', '--outdir', str(OUT)],
                   cwd=ROOT, capture_output=True, text=True)
if r.returncode: sys.exit(r.stdout + r.stderr)
print('  wrote', (OUT / 'SYNTH01_clean.csv').stat().st_size // 1000, 'kB')

print('\n== viewer export ==')
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
    pg.goto((ROOT / 'viewer/cath_viewer.html').as_uri())
    pg.wait_for_load_state('networkidle')
    pg.set_input_files('#picker', [str(ROOT / 'sample/SYNTH01.inf'),
                                   str(ROOT / 'sample/SYNTH01.bin'),
                                   str(ROOT / 'sample/SYNTH01.docx')])
    pg.wait_for_timeout(2500)
    cli = pg.locator('#cli').inner_text()
    print('  generated command:', cli)
    check('generated command carries --log', '--log' in cli and '--log-anchor header' in cli, cli)
    hint = pg.locator('#expHint').inner_text()
    check('export panel says events are included', 'event columns' in hint, hint)
    # headless has no file picker UI, so force the in-memory Blob path
    pg.evaluate('delete window.showSaveFilePicker; delete window.showDirectoryPicker;')
    with pg.expect_download(timeout=180000) as dl:
        pg.click('#expAll')
    dl.value.save_as(str(OUT / 'viewer_full.csv'))
    b.close()

print('\n== compare ==')
pyf = pd.read_csv(OUT / 'SYNTH01_clean.csv', low_memory=False)
vwf = pd.read_csv(OUT / 'viewer_full.csv', low_memory=False)
check('same row count', len(pyf) == len(vwf), f'{len(pyf)} vs {len(vwf)}')
check('viewer emits every event column', all(c in vwf.columns for c in EV),
      str([c for c in EV if c not in vwf.columns]))
check('python emits every event column', all(c in pyf.columns for c in EV),
      str([c for c in EV if c not in pyf.columns]))
check('same column order for the event block',
      [c for c in vwf.columns if c in EV] == [c for c in pyf.columns if c in EV])

n = min(len(pyf), len(vwf))
for c in EV:
    if c not in pyf.columns or c not in vwf.columns: continue
    a, b_ = pyf[c].iloc[:n], vwf[c].iloc[:n]
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b_):
        same = ((a.isna() & b_.isna()) | ((a - b_).abs() < 1e-6)).all()
        bad = int((~((a.isna() & b_.isna()) | ((a - b_).abs() < 1e-6))).sum())
    else:
        a, b_ = a.fillna('').astype(str), b_.fillna('').astype(str)
        same = (a == b_).all(); bad = int((a != b_).sum())
    check(f'{c} matches', same, f'{bad} of {n} rows differ')

print('\n== spot values ==')
row = pyf[pyf.infl == 1].iloc[0]
print(f"  first inflated sample  t={row.t_sec}  n={row.infl_n}  "
      f"target={row.infl_target}  atm={row.infl_atm}  infl_t={row.infl_t}")
print(f"  inflated samples: python {int(pyf.infl.sum()):,}  viewer {int(vwf.infl.sum()):,}")
print(f"  events placed:    python {int((pyf.event.fillna('')!='').sum())}  "
      f"viewer {int((vwf.event.fillna('')!='').sum())}")

print('\n=== console errors ==='); [print('  ', e) for e in errs]
print(f'\n{len(fails)} failure(s)'); [print('  FAIL', f) for f in fails]
sys.exit(1 if (fails or errs) else 0)
