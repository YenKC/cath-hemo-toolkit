"""Cover the three follow-up changes: SpO2 colour, folder loading, resizable track/text."""
import sys, pathlib, shutil
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                    ROOT / 'tests/_out'); SHOT.mkdir(parents=True, exist_ok=True)
TMP = SHOT.parent / 'fixture'          # a synthetic 2-case tree, no PHI
fails, errs = [], []

def check(name, cond, detail=''):
    print(f'  {"ok  " if cond else "FAIL"} {name}' + (f'   {detail}' if not cond else ''))
    if not cond: fails.append(f'{name} :: {detail}')

# two folders holding the same synthetic case, so the chooser has something to choose
shutil.rmtree(TMP, ignore_errors=True)
for name in ('caseA', 'caseB'):
    d = TMP / name; d.mkdir(parents=True)
    for ext in ('inf', 'bin', 'docx'):
        shutil.copy(ROOT / f'sample/SYNTH01.{ext}', d / f'{name}.{ext}')
# caseB gets a recorder-style bin name, so its stem does not match its .inf --
# which is how real exports arrive, and what the size check has to see through
(TMP / 'caseB' / 'caseB.bin').rename(TMP / 'caseB' / 'EXPORT01.bin')

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1680, 'height': 940})
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
    pg.goto((ROOT / 'viewer/cath_viewer.html').as_uri())
    pg.wait_for_load_state('networkidle')

    print('\n== 1. folder picker, single case ==')
    pg.set_input_files('#dirPicker', str(TMP / 'caseA'))
    pg.wait_for_timeout(2500)
    check('recording opened from the folder', pg.evaluate('!!S.bin'))
    check('log auto-found in the folder', pg.evaluate('!!S.log'))
    check('no chooser for a single case', not pg.locator('#cmodal').is_visible())
    check('bin matched by size', pg.evaluate('S.n') == 36000, str(pg.evaluate('S.n')))

    print('\n== 2. SpO2 reads light blue ==')
    spo2 = pg.evaluate("""() => {
        const c = [...document.querySelectorAll('.vital')].find(v =>
            v.querySelector('.k').textContent.trim().toLowerCase() === 'spo2');
        if (!c) return null;
        const v = c.querySelector('.v');
        return {colour: getComputedStyle(v).color, text: v.textContent.trim(),
                src: (c.querySelector('.src')||{}).textContent || '',
                fromlog: c.classList.contains('fromlog')}; }""")
    print('   SpO2 cell:', spo2)
    check('SpO2 cell exists', spo2 is not None)
    check('SpO2 is the light blue token', spo2 and spo2['colour'] == 'rgb(127, 212, 255)',
          spo2 and spo2['colour'])
    check('SpO2 value came from the log', spo2 and '%' in spo2['text'], spo2 and spo2['text'])
    check('log provenance still captioned', spo2 and 'log' in spo2['src'], spo2 and spo2['src'])
    nbp = pg.evaluate("""() => {
        const c = [...document.querySelectorAll('.vital')].find(v =>
            v.querySelector('.k').textContent.trim().toLowerCase() === 'nbp');
        return c ? getComputedStyle(c.querySelector('.v')).color : null; }""")
    check('NBP stays the default colour, so SpO2 stands out', nbp == 'rgb(207, 224, 240)', str(nbp))

    print('\n== 3. resizable timeline track ==')
    h0 = pg.evaluate("getComputedStyle(document.getElementById('track')).height")
    pg.evaluate('setTrackH(70)')
    pg.wait_for_timeout(500)
    h1 = pg.evaluate("getComputedStyle(document.getElementById('track')).height")
    check('track grew', h0 == '22px' and h1 == '70px', f'{h0} -> {h1}')
    tick = pg.evaluate("""() => { const t = document.querySelector('#evbar .eb');
        return t ? getComputedStyle(t).height : null; }""")
    check('event bars grew with it', tick and abs(float(tick[:-2]) - 29.4) < 0.2, str(tick))
    labelled = pg.locator('#evbar .eb b').count()
    check('wide bars gained labels', labelled >= 1, f'{labelled} labelled')
    print(f'   {labelled} of {pg.locator("#evbar .eb").count()} inflation bars labelled')
    seg_h = pg.evaluate("""() => { const s = document.querySelector('#segs');
        return getComputedStyle(s).height; }""")
    check('segment layer tracks the height too', seg_h == '68px', seg_h)
    pg.screenshot(path=str(SHOT / '10_tall_track.png'))

    print('\n== 4. text size control ==')
    before = pg.evaluate("getComputedStyle(document.querySelector('.ev .nt')).fontSize")
    pg.fill('#evFont', '17'); pg.dispatch_event('#evFont', 'change')
    pg.wait_for_timeout(400)
    after = pg.evaluate("getComputedStyle(document.querySelector('.ev .nt')).fontSize")
    check('notes text scaled up', before == '11px' and after == '16px', f'{before} -> {after}')
    tx = pg.evaluate("getComputedStyle(document.querySelector('.ev .tx')).fontSize")
    check('event text scaled', tx == '17px', tx)
    check('canvas annotations follow', pg.evaluate('S.evFont') == 17, str(pg.evaluate('S.evFont')))
    pg.evaluate('seek(50)'); pg.wait_for_timeout(800)
    pg.screenshot(path=str(SHOT / '11_big_text.png'))
    pg.fill('#evFont', '12'); pg.dispatch_event('#evFont', 'change')
    pg.evaluate('setTrackH(22)'); pg.wait_for_timeout(400)

    print('\n== 5. folder with two cases opens a chooser ==')
    pg.set_input_files('#dirPicker', str(TMP))
    pg.wait_for_timeout(1500)
    check('chooser shown', pg.locator('#cmodal').is_visible())
    rows = pg.locator('#cList .case').all_inner_texts()
    print('   choices:', [r.replace('\n', ' | ') for r in rows])
    check('two cases listed', len(rows) == 2, str(len(rows)))
    check('each says what it found', all('case log found' in r for r in rows), str(rows))
    check('listed in a stable alphabetical order',
          rows[0].startswith('caseA/') and rows[1].startswith('caseB/'),
          str([r.split(chr(10))[0] for r in rows]))
    pg.locator('#cList .case').nth(1).click()
    pg.wait_for_timeout(2500)
    check('chooser closed', not pg.locator('#cmodal').is_visible())
    check('second case opened', pg.evaluate('S.inf.name') == 'caseB.inf',
          pg.evaluate('S.inf.name'))
    check('mismatched bin name resolved by size',
          pg.evaluate('S.bin.name') == 'EXPORT01.bin', pg.evaluate('S.bin.name'))
    check('its log loaded', pg.evaluate('S.log && S.log.name') == 'caseB.docx',
          str(pg.evaluate('S.log && S.log.name')))

    print('\n== 6. bin without inf is refused clearly ==')
    msg = {}
    pg.once('dialog', lambda d: (msg.update(t=d.message), d.dismiss()))
    pg.set_input_files('#picker', [str(TMP / 'caseA' / 'caseA.bin')])
    pg.wait_for_timeout(900)
    check('explains why a lone .bin cannot work',
          'no .inf' in msg.get('t', '') and 'float64' in msg.get('t', ''), msg.get('t', '')[:120])

    b.close()

shutil.rmtree(TMP, ignore_errors=True)
print('\n=== console errors ===')
for e in errs: print('  ', e)
print(f'\n{len(fails)} failure(s)')
for f in fails: print('  FAIL', f)
sys.exit(1 if (fails or errs) else 0)
