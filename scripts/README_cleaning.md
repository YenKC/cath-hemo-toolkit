# Cleaning pipeline — what it does and why

`clean_export.py` turns a raw GE `.inf`/`.bin` pair into analysis-ready CSVs.

```bash
PY=/Users/ykc/miniforge3/envs/ai_crt/bin/python

$PY scripts/clean_export.py sample/SYNTH01          # cleaned, validated defaults
$PY scripts/clean_export.py sample/SYNTH01 --raw    # untouched — decide for yourself
$PY scripts/clean_export.py sample/SYNTH01 --no-baseline --sat-threshold 4.5
```

Every default below was chosen by measuring this recording, not by habit. Re-check them
when a case arrives with different gain or channels — the script derives what it can
(ADC full scale, LSB) but the physiologic ranges are constants at the top of the file.

**Both exports exist for the reference recording**, so a colleague can diff them or start from raw and
apply their own rules. `_raw` is bit-for-bit what the recorder wrote: the 16-bit
overflow, the saturation, and the pre-case placeholder values are all still there.

## Outputs

| file | rows | what it is |
|---|---|---|
| `<stem>_clean.csv` / `<stem>_raw.csv` | one per sample (4.6 M) | `timestamp`, `t_sec`, then all 14 channels |
| `<stem>_{clean,raw}_trend.csv` | one per second (19 k) | HR, per-second pressure mean/min/max, per-channel validity |
| `<stem>_{clean,raw}_qc.txt` | — | the exact settings used, and what each step removed |

## Every step is a flag

| flag | default | effect |
|---|---|---|
| `--raw` | off | no cleaning at all; output named `_raw` |
| `--no-unwrap` | on | keep the 16-bit pressure overflow |
| `--no-sat-mask` / `--sat-threshold MV` | auto | keep saturated ECG, or set the rail manually |
| `--sat-pad S` | 0.012 | seconds dropped either side of a saturated run |
| `--no-baseline` / `--baseline-window S` | on / 0.2 | keep wander, or change the stage-1 median |
| `--no-live-mask` | on | keep transducer-off stretches |
| `--press-limit CH=LO:HI` | AO −40:300, PCW −40:150 | physiologic window, repeatable |
| `--press-pad S` | 0.25 | seconds of post-flush ringdown dropped |
| `--highpass HZ` / `--lowpass HZ` | off | optional band limiting (see below for why it's off) |
| `--trend-only` | off | skip the ~620 MB full-rate CSV |

The `_qc.txt` header records the exact command, so any export can be reproduced.

**Removed samples are empty fields, never zeros and never interpolated.** In pandas they
load as `NaN`. Any downstream aggregation must be NaN-aware (`nanmean`, not `mean`),
because a voided sample means "we do not know", not "zero".

`t_sec` is the authoritative time base (`sample_index / 240`). `timestamp` is derived by
adding `t_sec` to the `.inf` start time and is **not verified** — see the alignment
warning below.

## What is applied

**Pressure channels (PCW, AO)**

1. *Unwrap the 16-bit overflow.* When pressure exceeds the +409.4 mmHg full scale
   (2047 × 0.2 mmHg) the stored value wraps by exactly 65536 counts and appears as
   ≈ −12,700 mmHg. Adding 65536 × LSB restores it: `406.0, [413.8, 415.4, 417.2], 409.8`
   reconstructs a smooth peak. 1,334 samples in the reference recording. Left uncorrected these destroy
   any mean or filter applied to the channel.
2. *Void out-of-range samples* (AO/default −40…300 mmHg, PCW −40…150) **plus 0.25 s
   either side**, because the transducer rings after a flush and the ringdown is as
   unusable as the spike itself.
3. *Void stretches where the transducer is not live.* Judged per 10 s block: needs a
   plausible median and a real pulse pressure. In the reference recording this removes ~46 min per channel
   — mostly before the case starts and after it ends. PCW is genuinely intermittent
   (the port gets used episodically), so expect gaps mid-case; that is real, not a bug.

**ECG channels**

1. *Void ADC saturation.* Full scale is ±5 mV at 12 bits (LSB 2.44 µV). The threshold is
   derived from the data (0.998 × observed full scale) and only applied if the extreme
   value repeats more than 100 times, so a recording without clipping is left alone.
   Saturated runs are padded by 12 ms either side.
2. *Remove baseline wander* with a two-stage median (200 ms then 600 ms) estimated only
   from unsaturated samples, then subtracted. The 200 ms window is longer than any QRS,
   so the estimate follows the baseline and not the beat.

## What is deliberately NOT applied

- **No mains notch.** There is no 60 Hz component — the 60 Hz bin sits at 1.0–2.2× its
  neighbours, i.e. no peak at all.
- **No low-pass.** The recorder already band-limits: 40–70 Hz and 70–120 Hz each hold
  0.0% of signal power. Any extra low-pass would only remove real QRS content.
- **No resampling, no gap interpolation, no outlier "smoothing".** Voided samples stay
  voided so the analyst can see exactly how much of each measurement is real.

## Validation

Against the raw signal, on 22,994 beats of lead II:

| check | result |
|---|---|
| ST (J+60 vs PR) shift from cleaning | median **0.00 µV**, IQR [−9.2, +2.4] |
| baseline wander, lead II | 0.409 → **0.049 mV** (sd of 1 s medians) |
| baseline wander, V2 | 2.235 → **0.315 mV** |
| AO after unwrap | no residual wrap, range −40…292 mmHg |

ST is measured beat-relative, so a correct wander removal must leave it unchanged — and
it does, for the bulk of beats.

**The 3% caveat.** 2.93% of beats shift by more than the 100 µV clinical ST threshold.
These are not a filter artefact: the wander slope under them is 0.104 mV/0.3 s versus
0.051 elsewhere. A beat sitting on a steep baseline ramp has an unreliable ST measurement
*in the raw signal too*. Apply a per-beat wander-slope filter before any ST endpoint
rather than trusting either version on those beats.

## Known limitations of this dataset

- **Wall-clock alignment is unverified.** `4,630,804 / 240 = 19,295 s`, but the header's
  Start→Stop span is 19,803 s — **508 s unexplained**, and it is not padding (only 290
  duplicate frames in 4.6 M). Until the event log arrives and the offset is explained,
  align on `t_sec` and treat `timestamp` as approximate.
- **The precordial leads clip, and they are the ones that matter for LAD/LM.** After
  padding: V2 19.0% voided, V4 7.9%, V1/V3/V5/V6 3.3–4.7%. All six limb leads are clean
  (0.5–0.7%, and 0.00% inside the live window). The cause is motion-driven baseline
  wander pushing the signal into the rail, not R-wave amplitude — so a lower recording
  gain on future cases would largely fix it. Worth raising with the lab.
- **No event markers exist in these files.** The `.bin` is exactly `N × C × 8` bytes with
  zero left over; there is no annotation stream, and no NBP/SpO2/respiration channel.
  Procedure notes and NBP readings have to come from a separate Mac-Lab export.
