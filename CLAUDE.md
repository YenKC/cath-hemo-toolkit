# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context7 MCP

Consult Context7 for version-correct docs **before** answering or writing code, without being asked, whenever the task involves a third-party library, framework, SDK, API, or CLI tool — specifically: correct usage of a library or API, generating code against one, project scaffolding / init / config steps, version differences, or installation, integration, and migration questions. Do not answer these from memory.

Skip it for work confined to this project's own code: syntax fixes, renames, comments, simple refactors, and reasoning that doesn't depend on external docs.

Tools: `mcp__claude_ai_Context7__resolve-library-id` (resolve the package ID first), then `mcp__claude_ai_Context7__query-docs`. Load via ToolSearch if deferred.

## Project state

Public repo (`YenKC/cath-hemo-toolkit`) holding two tools that share one definition of every cleaning setting: `viewer/cath_viewer.html` (browser viewer, no build step) and `scripts/clean_export.py` (batch cleaning and CSV export). `sample/SYNTH01.{inf,bin,docx}` is synthetic and safe to use anywhere — regenerate with `scripts/make_sample.py` and `scripts/make_sample_log.py`. Real recordings live in `Data/` locally and are gitignored — see the patient-data section.

No build system and no test suite. `scripts/validate_cleaning.py` is the closest thing: it re-derives every validation number quoted in the docs from the bundled sample.

## The recording format (`.inf` + `.bin` pair)

Each recording is two files sharing a stem (e.g. `Data/Demo/CASE.inf` / `CASE.bin`).

`*.inf` is CRLF ASCII: `Key = Value` lines, then a `Channel Number  Channel Label` table. The three fields that matter for reading the binary are `Number of Channel`, `Points for Each Channel`, and `Data Sampling Rate`.

`*.bin` has **no header**. It is little-endian `float64`, **sample-interleaved**: shape `(points_per_channel, n_channels)` in C order — i.e. all 14 channels for t=0, then all 14 for t=1. It is *not* channel-major; reading it that way yields plausible-looking but meaningless traces, so this is worth getting right the first time. `points × channels × 8` must equal the file size exactly — use that identity to validate any new file before trusting it, and refuse to guess the layout when it fails.

Verified loader:

```python
import re, numpy as np

def load(stem):
    meta, labels = {}, []
    for line in open(stem + '.inf', encoding='latin-1'):
        m = re.match(r'\s*(\d+)\s+(\S+)\s*$', line)
        if m:
            labels.append(m.group(2))
        elif '=' in line:
            k, v = line.split('=', 1)
            meta[k.strip()] = v.strip()
    n, c = int(meta['Points for Each Channel']), int(meta['Number of Channel'])
    x = np.memmap(stem + '.bin', dtype='<f8', mode='r').reshape(n, c)
    return x, labels, meta
```

Always `memmap` — a multi-hour study runs to hundreds of megabytes and a full float64 load is not casual.

This gives you the **raw** array. For anything analytical use `scripts/clean_export.py` instead — raw carries two traps that silently corrupt results (see below).

### Two traps in the raw signal

- **Pressure channels wrap.** Above the +409.4 mmHg full scale (2047 × 0.2) the stored value wraps by exactly 65536 counts and reads ≈ −12,700 mmHg. Fix: `x[x < -1000] += 65536 * 0.2`. Unfixed, these wreck any mean or filter over the channel.
- **ECG saturates at the ADC rail, and railed samples fake ST changes.** A railed PR baseline and a railed J-point differ by zero, so an ST algorithm returns a confident, wrong answer. Mask saturation before measuring. Derive the threshold rather than hardcoding it: a ±5 mV, 12-bit channel rails at 2047 × 2.4414 µV = 4.9988 mV, so a threshold of 5.00 matches nothing. Precordial leads clip far more than limb leads, and they are the ones that carry anterior ischaemia.

### Channel semantics

A typical layout is the 12-lead ECG (`I II III aVR aVL aVF V1..V6`) in **mV** followed by pressure channels in **mmHg**, but the count and order vary by case — dual arterial lines for a CTO, AO + LV for aortic stenosis. Units are mixed across the array, so never reduce across the channel axis without splitting ECG from pressure first. Channel count and labels come from the `.inf`; index by label, never by position.

### The case log (`.docx` / `.odt`) — the third file of a case

The `.bin` has **no annotation stream** (the size is exactly `N × C × 8` with zero bytes spare) and no NBP/SpO2 channel. Everything the study regresses on comes from the Mac-Lab case-log document filed beside the recording.

Layout: a line holding **only a time** (`1:39:40 PM`), then the summary line, then any comment lines, repeated. Everything before the first timestamp is the patient-information block (name, MRN, `Study Date`) and is PHI. Both formats are ZIP containers — `word/document.xml` for `.docx`, `content.xml` for `.odt`; strip tags at `</w:p>`/`</text:p>` boundaries and unescape entities **after** stripping, never before.

Event lines seen in practice, all machine-parseable: `Balloon inflated for 7 sec @ 10 atm in the LM.` (duration, atmospheres and target vessel — 83/83 parsed cleanly across the two real cases), `Stent deployed for …`, `Thrombectomy: 10 cc out on the LM.`, `AO : 115/55/72, HR = 76, II`, `SpO2 98%; HR 81 bpm; 91/69/74 NBP; RR 61/min`, `Heparin 5000u/ml IC 2,000 units`, `SAT: AO 97.0%`, and supply lines like `NC Trek 4.0mm x 12mm 143cm As:Abbott …`.

### Timing caveats

- The header's `Start Time`/`Stop Time` are the case log's **first and last event times** — on one real case they match to the second. On another they were off by **5h24m**, which is enough to throw every event off the recording. Verify header against log per case; where they disagree, believe the log and treat sample index as the time base. The viewer scores both anchorings and warns.
- `Points for Each Channel / Data Sampling Rate` need not match the header's `Start Time`→`Stop Time` span, and in practice often does not — both real cases run ~12–13 min short of their header span. Where they disagree, samples do **not** map linearly onto wall clock. Both tools surface the discrepancy rather than hiding it.
- `Date` may be an export date rather than an acquisition date — it can fall on a different day from `Start Time`.
- **There is no clock inside the `.bin`.** `points × channels × 8` equals the file size with *zero* bytes spare on both real cases, no channel is monotonic, and no value is epoch-like — so the `.inf` header is the only wall clock and there is nothing to recover when it is wrong. Do not go looking again.
- **The one alignment check that works is physical, not temporal.** A pressure trace cannot start before the artery was punctured, so `--log` compares first-sustained-live arterial signal against the first logged access event. On the clock-verified case that gap is **+131 s** (puncture → sheath → catheter → zeroed transducer). On the case whose header disagrees with its log, the trace was live **966 s before** access was logged — impossible, and proof the first-event anchor is wrong by at least that much; a `--log-offset` of about −1100 s makes it read +131 s and pulls the HR fit from +748 s to +55 s. It shifts mean AO during inflation 107.9 → 119.2 mmHg, so this is not cosmetic.
- **Aligning the log from the data does not work here, and `--log-fit` will tell you so.** Fitting needs a quantity both sources record often *and* that moves: HR is charted 20-40 times but spreads only ~25% about its median (every offset over ~1500 s fits within 1 bpm), and AO moves plenty but is charted twice per case. The fix is upstream — ask the lab why a header disagrees with its own log.
- Pressure channels sit at flat placeholder values before the transducers go live, at both ends of a recording. Detect and drop that lead-in rather than assuming the record is physiologic from t=0.

## Tooling

**`scripts/clean_export.py <stem>`** → `<parent>/derived/`. Every cleaning step is a flag (`--raw`, `--no-baseline`, `--sat-threshold`, `--press-limit CH=LO:HI`, `--highpass`, …); `--raw` writes the signal untouched. Produce both for a case when someone needs to diff cleaned against untouched.

| file | rows | contents |
|---|---|---|
| `<stem>_clean.csv` / `<stem>_raw.csv` | one per sample | `timestamp`, `t_sec`, every channel |
| `<stem>_{clean,raw}_trend.csv` | one per second | HR, pressure mean/min/max, validity |
| `<stem>_{clean,raw}_events.csv` | one per log event | with `--log` |
| `<stem>_{clean,raw}_qc.txt` | — | exact command used + what each step removed |

`--log <case log>` folds the events into the signal rows: 16 columns covering the event text, the inflation state (`infl`, `infl_n`, `infl_target`, `infl_atm`, `infl_t`), the alignment pair (`peri_n`, `peri_t` = signed seconds to the nearest inflation), and charted vitals carried forward. `scripts/caselog.py` is the parser and is runnable on its own. **The viewer emits the identical columns in the identical order** — two implementations of one spec, cross-checked byte-for-byte; change them together.

Liveness masking (`LIVE_RULES`) answers only "is a transducer connected?", never "is this value normal". Bands are pattern-matched per channel and sized to pathology — severe TR puts RA in the 30s, acute MR puts wedge v waves past 50, severe PAH puts PA near 100 — and an unknown label gets the widest band, because deleting an unrecognised channel is worse than keeping some dead blocks. A block passes if its median is in range and it is either pulsatile or flat at a perfusing level; that last clause keeps non-pulsatile **ECMO/bypass** arterial traces, which pulsatility alone cannot distinguish from a disconnected line. The old single rule required median > 30 mmHg of every pressure channel and deleted 99.5% of a real RA trace.

Voided samples are **empty fields, never zeros and never interpolated** — aggregate with `nanmean`, not `mean`. Deliberately not applied: no mains notch (no 60 Hz component exists) and no low-pass (the recorder already band-limits; 40–120 Hz holds 0.0% of power). Rationale, validation numbers, and tuning constants: `scripts/README_cleaning.md` — read it before changing a threshold.

The full-rate CSV exceeds Excel's 1,048,576-row cap. Use `_trend.csv` for browsing, pandas for the full file.

**`viewer/cath_viewer.html`** — zero-install Mac-Lab-style viewer, the single file a colleague needs. Opens the `.inf`/`.bin` pair via byte-range slicing, so open time is independent of recording length and any point costs the same as any other, with live cleaning controls, In/Out segment trimming, and CSV export of a window, a segment, or the whole study. It generates the matching `clean_export.py` command — including `--start`/`--stop` — so settings tuned on screen reproduce exactly in batch. A right-hand panel loads the case log, places its events on the timeline (inflations as intervals, not pins), fills the NBP/SpO2 footer slots the `.bin` has no channel for, and exports the event table. Footer numbers are **window aggregates**, so a hover/pinnable time cursor gives per-trace values at a single instant — that is the tool for checking a logged value against the trace. Details in `viewer/README.md`.

The primary way in is a **folder** — dropped on the window or via Open folder — because a browser cannot see the directory around a single `File`; that is a security boundary, so "just pick the `.bin` and find the rest" is not implementable and the folder path is the honest substitute. A folder of several cases opens a chooser. Given several `.bin` files it picks the one whose size matches the header and reports a swap rather than trusting the filename — two of the first three real cases were filed under the wrong stem.

Two invariants to preserve when editing it:
- **No network code.** Local file reads only — that is what makes handling PHI in a browser acceptable. The `.docx`/`.odt` reader is a hand-rolled ZIP walk plus `DecompressionStream`; do not reach for a library.
- **Nothing hardwired to one layout.** Channel count, names, and order come from the `.inf`; type is auto-detected (standard lead names, else ADC step: ECG ≈0.0024 mV vs pressure 0.2 mmHg) and user-overridable. Real cases carry two AO lines (dual-access CTO) or AO + LV (AS), so colours and footer readouts are per channel, never per fixed role.

Note the `.inf` clock is naive local time and the Python exporter keeps it that way. Anything formatting timestamps must use local time — `toISOString()` silently shifts by the UTC offset.

## Patient data — never commit it

`Data/` holds identifiable PHI: the `.inf` sidecar carries a patient name in cleartext and the waveforms are identifiable health information. `.gitignore` excludes `Data/`, every `derived/` folder, and all `.bin`/`.inf`/`.csv` files, with a single negation for `sample/SYNTH01.*`. **Keep it that way** — this repository is public.

Do not paste `.inf` contents into commits, issues, artifacts, or any external service, and de-identify anything derived from a real recording before sharing it. Use `sample/SYNTH01` (from `scripts/make_sample.py`) for screenshots, demos, and bug reports.
