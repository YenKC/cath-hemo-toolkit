"""Drive the viewer against the synthetic case + synthetic log."""
import sys, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'tests/_out')
SHOT.mkdir(parents=True, exist_ok=True)

errs, logs = [], []
fails = []

def check(name, cond, detail=''):
    (print(f'  ok   {name}') if cond else fails.append(f'{name} :: {detail}'))
    if not cond:
        print(f'  FAIL {name}  {detail}')

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1680, 'height': 940})
    pg.on('console', lambda m: (logs.append(m.text), errs.append(m.text) if m.type == 'error' else None))
    pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))

    pg.goto((ROOT / 'viewer/cath_viewer.html').as_uri())
    pg.wait_for_load_state('networkidle')

    print('\n== load recording + log together ==')
    pg.set_input_files('#picker', [str(ROOT / 'sample/SYNTH01.inf'),
                                   str(ROOT / 'sample/SYNTH01.bin'),
                                   str(ROOT / 'sample/SYNTH01.docx')])
    pg.wait_for_timeout(2500)

    check('log panel visible', pg.locator('#logside').is_visible())
    n = pg.locator('#logList .ev').count()
    check('21 event rows', n == 21, f'got {n}')
    ttl = pg.locator('#logTtl').inner_text().lower()
    src = pg.locator('#logSrc').inner_text()
    check('title counts the events', '21 events' in ttl, ttl)
    check('source line names the file, un-uppercased', src == 'SYNTH01.docx', src)

    chips = pg.locator('#logChips .chip').all_inner_texts()
    print('   chips:', chips)
    kinds = {c.split()[0] for c in chips}
    for want in ('inflation', 'vitals', 'pressure', 'med', 'lab', 'procedure', 'device'):
        check(f'chip {want}', want in kinds, str(kinds))

    warn_on = pg.locator('#logWarn').evaluate('e => e.classList.contains("on")')
    check('no spurious warning for a matching log', not warn_on,
          pg.locator('#logWarn').inner_text())
    anchor = pg.locator('#logAnchor').input_value()
    check('anchored to the .inf Start Time', anchor == 'header', anchor)

    # the first inflation is at 9:00:52, i.e. t = 52 s
    first_inf = pg.locator('#logList .ev', has_text='Balloon inflated for 12 sec').first
    check('first inflation row present', first_inf.count() > 0)
    tm = first_inf.locator('.tm').inner_text().strip()
    check('inflation mapped to 0:00:52', tm == '0:00:52', tm)
    kd = first_inf.locator('.kd').inner_text()
    check('inflation shows duration, atm and target',
          '12 s' in kd and '8 atm' in kd and 'pLAD' in kd, kd)

    print('\n== click an event to seek ==')
    first_inf.click()
    pg.wait_for_timeout(900)
    t0 = pg.evaluate('S.t0')
    check('seeked near the inflation', 45 <= t0 <= 53, f't0={t0}')
    pg.screenshot(path=str(SHOT / '01_inflation.png'))

    print('\n== footer picks up NBP/SpO2 from the log ==')
    vit = pg.locator('#vitals').inner_text().replace('\n', ' | ')
    print('   vitals:', vit)
    check('NBP came from the log', '132/74/94' in vit or '121/70/87' in vit, vit)
    check('SpO2 came from the log', '%' in vit, vit)
    check('log-sourced cells are labelled', pg.locator('.vital.fromlog').count() >= 2)

    print('\n== filter to inflations only ==')
    for c in pg.locator('#logChips .chip').all():
        if not c.inner_text().startswith('inflation'):
            c.click()
    pg.wait_for_timeout(600)
    n2 = pg.locator('#logList .ev').count()
    check('4 inflations remain', n2 == 4, f'got {n2}')
    pg.screenshot(path=str(SHOT / '02_filtered.png'))

    print('\n== N steps balloon to balloon ==')
    before = pg.evaluate('S.t0')
    pg.locator('#logNext').click()
    pg.wait_for_timeout(700)
    after = pg.evaluate('S.t0')
    check('N advanced to the next inflation', after > before, f'{before} -> {after}')

    print('\n== search box ==')
    pg.fill('#logSearch', 'stent')
    pg.wait_for_timeout(500)
    n3 = pg.locator('#logList .ev').count()
    check('search narrows to the stent', n3 == 1, f'got {n3}')
    pg.fill('#logSearch', '')
    for c in pg.locator('#logChips .chip').all():
        if c.get_attribute('class').endswith('off'):
            c.click()
    pg.wait_for_timeout(500)

    print('\n== nudge / anchor controls ==')
    pg.fill('#logOff', '30')
    pg.dispatch_event('#logOff', 'change')
    pg.wait_for_timeout(500)
    tm2 = pg.locator('#logList .ev', has_text='Balloon inflated for 12 sec').first.locator('.tm').inner_text().strip()
    check('nudge shifted events by 30 s', tm2 == '0:01:22', tm2)
    pg.fill('#logOff', '0')
    pg.dispatch_event('#logOff', 'change')
    pg.wait_for_timeout(400)

    print('\n== events CSV ==')
    with pg.expect_download() as dl:
        pg.click('#expEvents')
    path = dl.value.path()
    csv = pathlib.Path(path).read_text()
    rows = [r for r in csv.strip().split('\n')]
    check('csv has header + 21 rows', len(rows) == 22, f'got {len(rows)}')
    check('csv header has the study fields',
          all(k in rows[0] for k in ('t_sec', 'kind', 'dur_s', 'atm', 'target', 'nbp')), rows[0])
    inf_row = [r for r in rows if 'Balloon inflated for 12' in r][0]
    print('   inflation row:', inf_row[:150])
    check('inflation row carries t_sec/dur/atm/target',
          inf_row.startswith('52.0,') and ',12,8,pLAD,' in inf_row, inf_row[:120])
    (SHOT / 'events.csv').write_text(csv)

    print('\n== unload ==')
    pg.click('#logClose')
    pg.wait_for_timeout(400)
    check('panel hidden after unload', not pg.locator('#logside').is_visible())
    check('track ticks cleared', pg.locator('#evbar div').count() == 0)

    print('\n== reload log alone onto the open case ==')
    pg.set_input_files('#logPicker', str(ROOT / 'sample/SYNTH01.docx'))
    pg.wait_for_timeout(1200)
    check('panel back', pg.locator('#logside').is_visible())
    check('track ticks drawn', pg.locator('#evbar div').count() >= 20,
          str(pg.locator('#evbar div').count()))
    pg.evaluate('seek(46)')
    pg.wait_for_timeout(900)
    pg.screenshot(path=str(SHOT / '03_final.png'))

    # worst case for the tint: window sitting wholly inside the 18 s inflation at t=74
    pg.evaluate('seek(78)')
    pg.wait_for_timeout(900)
    pg.screenshot(path=str(SHOT / '04_inside_inflation.png'))

    # a burst: 30 s window over the stent + post-dilatation run
    pg.select_option('#winLen', '30')
    pg.wait_for_timeout(300)
    pg.evaluate('seek(70)')
    pg.wait_for_timeout(1000)
    pg.screenshot(path=str(SHOT / '05_burst.png'))

    b.close()

print('\n=== console errors ===')
for e in errs:
    print('  ', e)
print(f'\n{len(fails)} failure(s)')
for f in fails:
    print('  FAIL', f)
sys.exit(1 if (fails or errs) else 0)
