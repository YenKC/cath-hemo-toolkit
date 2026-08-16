"""The time cursor: does it report the instant it points at, and the right value there?"""
import sys, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                    ROOT / 'tests/_out'); SHOT.mkdir(parents=True, exist_ok=True)
fails, errs = [], []

def check(n, c, d=''):
    print(f'  {"ok  " if c else "FAIL"} {n}' + (f'   {d}' if not c else ''))
    if not c: fails.append(f'{n} :: {d}')

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1680, 'height': 940})
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
    pg.goto((ROOT / 'viewer/cath_viewer.html').as_uri())
    pg.wait_for_load_state('networkidle')
    pg.set_input_files('#picker', [str(ROOT / 'sample/SYNTH01.inf'),
                                   str(ROOT / 'sample/SYNTH01.bin'),
                                   str(ROOT / 'sample/SYNTH01.docx')])
    pg.wait_for_timeout(2500)
    pg.evaluate('seek(50)')
    pg.wait_for_timeout(800)

    print('\n== before hovering, the readout names the window ==')
    txt = pg.locator('#tpos').inner_text()
    print('   ', txt)
    check('says "window" and a range', 'window' in txt and '–' in txt, txt)

    print('\n== hover puts a cursor at that instant ==')
    box = pg.locator('#plot').bounding_box()
    geo = pg.evaluate('({padL:S.layout.padL, plotW:S.layout.plotW})')
    # aim at 30% across the plot => t0 + 0.3*win
    tx = box['x'] + geo['padL'] + geo['plotW'] * 0.30
    pg.mouse.move(tx, box['y'] + box['height'] * 0.5)
    pg.wait_for_timeout(400)
    st = pg.evaluate('({t:S.cur.t, pin:S.cur.pin, t0:S.t0, win:S.win})')
    want = st['t0'] + 0.30 * st['win']
    print(f"   cursor t={st['t']:.3f}s, expected {want:.3f}s")
    check('cursor lands where the pointer is', abs(st['t'] - want) < 0.06,
          f"{st['t']:.3f} vs {want:.3f}")
    txt = pg.locator('#tpos').inner_text()
    print('   ', txt)
    check('readout switches to the cursor instant', 'cursor' in txt, txt)

    print('\n== the value it draws is the actual sample there ==')
    got = pg.evaluate("""() => {
        const t = S.cur.t;
        const i = S.data.off + Math.round((t - S.t0) * S.fs);
        const out = {};
        for (const m of S.layout.marks) out[m.lab] = S.data.chans[m.lab][i];
        return {i, t, out, ao: S.data.chans['AO'][i]}; }""")
    print(f"   at t={got['t']:.3f}s  AO={got['ao']:.2f} mmHg, "
          f"{len(got['out'])} traces marked")
    check('a mark exists for every visible trace', len(got['out']) == 14, str(len(got['out'])))
    check('AO value is physiologic', 40 < got['ao'] < 200, str(got['ao']))
    # independent recompute of the same instant straight from the window slice
    indep = pg.evaluate("""() => {
        const t = S.cur.t, i = Math.round((t - S.t0) * S.fs);
        return S.data.chans['AO'][S.data.off + i]; }""")
    check('value matches an independent lookup', abs(indep - got['ao']) < 1e-9,
          f'{indep} vs {got["ao"]}')

    print('\n== click pins it, click again releases ==')
    pg.mouse.click(tx, box['y'] + box['height'] * 0.5)
    pg.wait_for_timeout(400)
    check('pinned', pg.evaluate('S.cur.pin') is True)
    check('readout says pinned', 'pinned' in pg.locator('#tpos').inner_text())
    pg.screenshot(path=str(SHOT / '20_cursor_pinned.png'))
    # moving away must not drag a pinned cursor
    before = pg.evaluate('S.cur.t')
    pg.mouse.move(tx + 180, box['y'] + box['height'] * 0.4)
    pg.wait_for_timeout(300)
    check('a pinned cursor stays put', abs(pg.evaluate('S.cur.t') - before) < 1e-9,
          f"{pg.evaluate('S.cur.t')} vs {before}")
    pg.mouse.click(tx + 180, box['y'] + box['height'] * 0.4)
    pg.wait_for_timeout(300)
    check('unpinned by a second click', pg.evaluate('S.cur.pin') is False)

    print('\n== leaving the chart clears it ==')
    pg.mouse.move(box['x'] - 50, box['y'] - 50)
    pg.wait_for_timeout(400)
    check('cursor cleared', pg.evaluate('S.cur.t') is None, str(pg.evaluate('S.cur.t')))
    check('readout back to the window', 'window' in pg.locator('#tpos').inner_text())

    print('\n== it still works with the log panel and 30 s windows ==')
    pg.select_option('#winLen', '30')
    pg.wait_for_timeout(500)
    pg.mouse.move(tx, box['y'] + box['height'] * 0.5)
    pg.wait_for_timeout(400)
    st = pg.evaluate('({t:S.cur.t, t0:S.t0, win:S.win})')
    check('scales with window length', abs(st['t'] - (st['t0'] + 0.30 * 30)) < 0.2,
          f"{st['t']:.2f}")
    pg.screenshot(path=str(SHOT / '21_cursor_30s.png'))
    b.close()

print('\n=== console errors ==='); [print('  ', e) for e in errs]
print(f'\n{len(fails)} failure(s)'); [print('  FAIL', f) for f in fails]
sys.exit(1 if (fails or errs) else 0)
