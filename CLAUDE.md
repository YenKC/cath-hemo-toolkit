# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context7 MCP

Consult Context7 for version-correct docs **before** answering or writing code, without being asked, whenever the task involves a third-party library, framework, SDK, API, or CLI tool — specifically: correct usage of a library or API, generating code against one, project scaffolding / init / config steps, version differences, or installation, integration, and migration questions. Do not answer these from memory.

Skip it for work confined to this project's own code: syntax fixes, renames, comments, simple refactors, and reasoning that doesn't depend on external docs.

Tools: `mcp__claude_ai_Context7__resolve-library-id` (resolve the package ID first), then `mcp__claude_ai_Context7__query-docs`. Load via ToolSearch if deferred.

## Project state

Public repo (`YenKC/cath-hemo-toolkit`) holding two tools that share one definition of every cleaning setting: `viewer/cath_viewer.html` (browser viewer, no build step) and `scripts/clean_export.py` (batch cleaning and CSV export). `sample/SYNTH01.{inf,bin}` is synthetic and safe to use anywhere. Real recordings live in `Data/` locally and are gitignored — see the patient-data section.

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

### Timing caveats

- `Points for Each Channel / Data Sampling Rate` need not match the header's `Start Time`→`Stop Time` span, and in practice often does not. Where they disagree, samples do **not** map linearly onto wall clock: treat sample index as the only reliable time base and the header times as approximate anchors. Both tools surface the discrepancy rather than hiding it.
- `Date` may be an export date rather than an acquisition date — it can fall on a different day from `Start Time`.
- Pressure channels sit at flat placeholder values before the transducers go live, at both ends of a recording. Detect and drop that lead-in rather than assuming the record is physiologic from t=0.

## Tooling

**`scripts/clean_export.py <stem>`** → `<parent>/derived/`. Every cleaning step is a flag (`--raw`, `--no-baseline`, `--sat-threshold`, `--press-limit CH=LO:HI`, `--highpass`, …); `--raw` writes the signal untouched. Produce both for a case when someone needs to diff cleaned against untouched.

| file | rows | contents |
|---|---|---|
| `<stem>_clean.csv` / `<stem>_raw.csv` | one per sample | `timestamp`, `t_sec`, every channel |
| `<stem>_{clean,raw}_trend.csv` | one per second | HR, pressure mean/min/max, validity |
| `<stem>_{clean,raw}_qc.txt` | — | exact command used + what each step removed |

Voided samples are **empty fields, never zeros and never interpolated** — aggregate with `nanmean`, not `mean`. Deliberately not applied: no mains notch (no 60 Hz component exists) and no low-pass (the recorder already band-limits; 40–120 Hz holds 0.0% of power). Rationale, validation numbers, and tuning constants: `scripts/README_cleaning.md` — read it before changing a threshold.

The full-rate CSV exceeds Excel's 1,048,576-row cap. Use `_trend.csv` for browsing, pandas for the full file.

**`viewer/cath_viewer.html`** — zero-install Mac-Lab-style viewer, the single file a colleague needs. Opens the `.inf`/`.bin` pair via byte-range slicing, so open time is independent of recording length and any point costs the same as any other, with live cleaning controls, In/Out segment trimming, and CSV export of a window, a segment, or the whole study. It generates the matching `clean_export.py` command — including `--start`/`--stop` — so settings tuned on screen reproduce exactly in batch. Details in `viewer/README.md`.

Two invariants to preserve when editing it:
- **No network code.** Local file reads only — that is what makes handling PHI in a browser acceptable.
- **Nothing hardwired to one layout.** Channel count, names, and order come from the `.inf`; type is auto-detected (standard lead names, else ADC step: ECG ≈0.0024 mV vs pressure 0.2 mmHg) and user-overridable. Real cases carry two AO lines (dual-access CTO) or AO + LV (AS), so colours and footer readouts are per channel, never per fixed role.

Note the `.inf` clock is naive local time and the Python exporter keeps it that way. Anything formatting timestamps must use local time — `toISOString()` silently shifts by the UTC offset.

## Patient data — never commit it

`Data/` holds identifiable PHI: the `.inf` sidecar carries a patient name in cleartext and the waveforms are identifiable health information. `.gitignore` excludes `Data/`, every `derived/` folder, and all `.bin`/`.inf`/`.csv` files, with a single negation for `sample/SYNTH01.*`. **Keep it that way** — this repository is public.

Do not paste `.inf` contents into commits, issues, artifacts, or any external service, and de-identify anything derived from a real recording before sharing it. Use `sample/SYNTH01` (from `scripts/make_sample.py`) for screenshots, demos, and bug reports.
