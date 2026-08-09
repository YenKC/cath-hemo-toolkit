# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context7 MCP

Consult Context7 for version-correct docs **before** answering or writing code, without being asked, whenever the task involves a third-party library, framework, SDK, API, or CLI tool — specifically: correct usage of a library or API, generating code against one, project scaffolding / init / config steps, version differences, or installation, integration, and migration questions. Do not answer these from memory.

Skip it for work confined to this project's own code: syntax fixes, renames, comments, simple refactors, and reasoning that doesn't depend on external docs.

Tools: `mcp__claude_ai_Context7__resolve-library-id` (resolve the package ID first), then `mcp__claude_ai_Context7__query-docs`. Load via ToolSearch if deferred.

## Project state

Data-only at present: no source code, no build system, no tests, and not a git repository. The single asset is a cardiac catheterization lab recording under `Data/Demo/`. Anything written here is the first code in the project — pick structure deliberately rather than assuming one exists.

## The recording format (`.inf` + `.bin` pair)

Each recording is two files sharing a stem (e.g. `Data/Demo/CASE.inf` / `CASE.bin`).

`*.inf` is CRLF ASCII: `Key = Value` lines, then a `Channel Number  Channel Label` table. The three fields that matter for reading the binary are `Number of Channel`, `Points for Each Channel`, and `Data Sampling Rate`.

`*.bin` has **no header**. It is little-endian `float64`, **sample-interleaved**: shape `(points_per_channel, n_channels)` in C order — i.e. all 14 channels for t=0, then all 14 for t=1. It is *not* channel-major; reading it that way yields plausible-looking but meaningless traces, so this is worth getting right the first time. For the reference recording: 4,630,804 × 14 × 8 = 518,650,048 bytes, exactly the file size — use that identity to validate any new file before trusting it.

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

Always `memmap` — the demo file is 495 MB and a full float64 load of a longer study will not be casual.

This gives you the **raw** array. For anything analytical use `scripts/clean_export.py` instead — raw carries two traps that silently corrupt results (see below).

### Two traps in the raw signal

- **Pressure channels wrap.** Above the +409.4 mmHg full scale (2047 × 0.2) the stored value wraps by exactly 65536 counts and reads ≈ −12,700 mmHg. Fix: `x[x < -1000] += 65536 * 0.2`. Unfixed, these wreck any mean or filter over the channel.
- **ECG saturates at ±5 mV, and railed samples fake ST changes.** A railed PR baseline and a railed J-point differ by zero, so an ST algorithm returns a confident, wrong answer. Always mask `|v| >= 4.99` before measuring. Limb leads are clean (0.00% inside the live window); V2 rails 15.6%, V4 5.5% — and those are the leads that matter for LAD/LM.

### Channel semantics

The reference recording is 14 channels at 240 Hz: the 12-lead ECG (`I II III aVR aVL aVF V1..V6`) in **mV**, then `PCW` (pulmonary capillary wedge) and `AO` (aortic) pressures in **mmHg**. Units are mixed across the array — never reduce across the channel axis without splitting ECG from pressure first. Channel count and labels come from the `.inf`; index by label, not by hardcoded position.

### Timing caveats

- `Points for Each Channel / Data Sampling Rate` gives 19,295 s, but the header's `Start Time`→`Stop Time` span is 19,803 s. The ~508 s difference means samples do **not** map linearly onto wall clock; treat sample index as the only reliable time base and the header times as approximate anchors.
- `Date` (8/5/2026) is a different day from `Start Time`/`Stop Time` (7/9/2026) — likely an export date, not an acquisition date.
- Pressure channels sit at flat placeholder values (`AO = -3.0`, `PCW = 0.4`) at the start of the file, before the transducers are live. Detect and drop this lead-in rather than assuming the record is physiologic from t=0.

## Tooling

**`scripts/clean_export.py <stem>`** → `Data/Demo/derived/`. Every cleaning step is a flag (`--raw`, `--no-baseline`, `--sat-threshold`, `--press-limit CH=LO:HI`, `--highpass`, …); `--raw` writes the signal untouched. Both `_clean` and `_raw` exports exist for the reference recording.

| file | rows | contents |
|---|---|---|
| `<stem>_clean.csv` / `<stem>_raw.csv` | 4.6 M (622 / 645 MB) | `timestamp`, `t_sec`, all 14 channels |
| `<stem>_{clean,raw}_trend.csv` | 19 k | per-second HR, pressure mean/min/max, validity |
| `<stem>_{clean,raw}_qc.txt` | — | exact command used + what each step removed |

Voided samples are **empty fields, never zeros and never interpolated** — aggregate with `nanmean`, not `mean`. Deliberately not applied: no mains notch (no 60 Hz component exists) and no low-pass (the recorder already band-limits; 40–120 Hz holds 0.0% of power). Rationale, validation numbers, and tuning constants: `scripts/README_cleaning.md` — read it before changing a threshold.

The full-rate CSV exceeds Excel's 1,048,576-row cap. Use `_trend.csv` for browsing, pandas for the full file.

**`viewer/cath_viewer.html`** — zero-install Mac-Lab-style viewer, the single file a colleague needs. Opens the `.inf`/`.bin` pair via byte-range slicing (519 MB file opens in 99 ms; hour 4 costs the same as hour 0), with live cleaning controls, In/Out segment trimming, and CSV export of a window, a segment, or the whole study. It generates the matching `clean_export.py` command — including `--start`/`--stop` — so settings tuned on screen reproduce exactly in batch. Details in `viewer/README.md`.

Two invariants to preserve when editing it:
- **No network code.** Local file reads only — that is what makes handling PHI in a browser acceptable.
- **Nothing hardwired to one layout.** Channel count, names, and order come from the `.inf`; type is auto-detected (standard lead names, else ADC step: ECG ≈0.0024 mV vs pressure 0.2 mmHg) and user-overridable. Real cases carry two AO lines (dual-access CTO) or AO + LV (AS), so colours and footer readouts are per channel, never per fixed role.

Note the `.inf` clock is naive local time and the Python exporter keeps it that way. Anything formatting timestamps must use local time — `toISOString()` silently shifts by the UTC offset.

## Patient data — never commit it

`Data/` holds identifiable PHI: the `.inf` sidecar carries a patient name in cleartext and the waveforms are identifiable health information. `.gitignore` excludes `Data/`, every `derived/` folder, and all `.bin`/`.inf`/`.csv` files, with a single negation for `sample/SYNTH01.*`. **Keep it that way** — this repository is public.

Do not paste `.inf` contents into commits, issues, artifacts, or any external service, and de-identify anything derived from a real recording before sharing it. Use `sample/SYNTH01` (from `scripts/make_sample.py`) for screenshots, demos, and bug reports.

## Local development

`scripts/` needs Python 3.10+ with numpy, scipy, and pandas. On this machine the `python3` first on `PATH` is system Python 3.9 with **no numpy** and will fail immediately; use a conda env instead — `~/miniforge3/envs/ai_crt` has the full stack.

```
/Users/ykc/miniforge3/envs/ai_crt/bin/python scripts/clean_export.py sample/SYNTH01
```

There is no project-local environment or dependency manifest; `uv` is installed if one is wanted.

`scripts/make_sample.py` regenerates `sample/SYNTH01.{inf,bin}` — 150 s of synthetic signal carrying both traps, safe to commit and to screenshot.
