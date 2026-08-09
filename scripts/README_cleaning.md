# Cleaning pipeline — what it does and why

`clean_export.py` turns a raw GE `.inf`/`.bin` pair into analysis-ready CSVs.

```bash
python scripts/clean_export.py sample/SYNTH01          # cleaned, validated defaults
python scripts/clean_export.py sample/SYNTH01 --raw    # untouched — decide for yourself
python scripts/clean_export.py sample/SYNTH01 --no-baseline --sat-threshold 4.5
```

Set the environment up once with `pip install -r requirements.txt` or
`conda env create -f environment.yml`.

Every default below was chosen by measuring a recording rather than by habit, and each
one says what it was measuring. Re-check them when a case arrives with a different gain or
channel set: the script derives what it can from the file itself (ADC full scale, LSB), but
the physiologic ranges are constants at the top of `clean_export.py`.

**Produce both for a case** and a colleague can diff them, or start from raw and apply
their own rules. `_raw` is bit-for-bit what the recorder wrote: the 16-bit overflow, the
saturation, and the pre-case placeholder values are all still there.

## Outputs

| file | rows | what it is |
|---|---|---|
| `<stem>_clean.csv` / `<stem>_raw.csv` | one per sample | `timestamp`, `t_sec`, then every channel |
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

`t_sec` is the authoritative time base (`sample_index / sample_rate`). `timestamp` is derived by
adding `t_sec` to the `.inf` start time and is **not verified** — see the alignment
warning below.

## What is applied

**Pressure channels (PCW, AO)**

1. *Unwrap the 16-bit overflow.* When pressure exceeds the +409.4 mmHg full scale
   (2047 × 0.2 mmHg) the stored value wraps by exactly 65536 counts and appears as
   ≈ −12,700 mmHg. Adding 65536 × LSB restores it: `406.0, [413.8, 415.4, 417.2], 409.8`
   reconstructs a smooth peak. A flush or contrast injection triggers this routinely.
   Left uncorrected these destroy any mean or filter applied to the channel.
2. *Void out-of-range samples* (AO/default −40…300 mmHg, PCW −40…150) **plus 0.25 s
   either side**, because the transducer rings after a flush and the ringdown is as
   unusable as the spike itself.
3. *Void stretches where the transducer is not live.* Judged per 10 s block: needs a
   plausible median and a real pulse pressure. Most of what this removes sits before the
   case starts and after it ends. A wedge port is genuinely intermittent — it gets used
   episodically — so expect gaps mid-case on that channel; those are real, not a bug.

**ECG channels**

1. *Void ADC saturation.* Full scale is ±5 mV at 12 bits (LSB 2.44 µV). The threshold is
   derived from the data (0.998 × observed full scale) and only applied if the extreme
   value repeats more than 100 times, so a recording without clipping is left alone.
   Saturated runs are padded by 12 ms either side.
2. *Remove baseline wander* with a two-stage median (200 ms then 600 ms) estimated only
   from unsaturated samples, then subtracted. The 200 ms window is longer than any QRS,
   so the estimate follows the baseline and not the beat.

## What is deliberately NOT applied

- **No mains notch.** The recorder this was built against carries no mains component —
  the 50/60 Hz bin sits level with its neighbours, so a notch would remove signal and no
  noise. Check the spectrum of your own recorder before deciding otherwise.
- **No low-pass.** The same recorder already band-limits below about 40 Hz, leaving
  essentially no power above it, so an extra low-pass would only remove real QRS content.
  Both filters are exposed as flags for recorders that behave differently.
- **No resampling, no gap interpolation, no outlier "smoothing".** Voided samples stay
  voided so the analyst can see exactly how much of each measurement is real.

## Validation

```bash
python scripts/validate_cleaning.py              # the bundled sample
python scripts/validate_cleaning.py path/to/CASE # your own recording
```

Against the raw signal, on the bundled synthetic sample:

| check | result |
|---|---|
| ST (J+60 vs PR) shift from cleaning | median **−1.7 µV**, IQR [−20.9, +5.7] |
| beats shifted past the 100 µV clinical threshold | **0.00%** |
| baseline wander, lead II | 0.074 → **0.003 mV** (sd of 1 s medians) |
| baseline wander, V2 (motion artefact) | 0.827 → **0.117 mV** |
| pressure after unwrap | no residual wrap |

ST is measured beat-relative, so a correct wander removal must leave it unchanged — and
it does. Run the same script against your own file: the numbers that matter are yours,
not these.

**Expect a residual on steep-wander beats.** On a real recording with heavy electrode
motion, a small percentage of beats will shift past 100 µV. That is not a filter artefact
— a beat sitting on a steep baseline ramp has an unreliable ST measurement *in the raw
signal too*. Apply a per-beat wander-slope filter before any ST endpoint rather than
trusting either version on those beats.

## Check these in every new recording

Recorder settings, electrode contact, and which ports were used all differ case to case,
so the defaults here are a starting point rather than a specification. Before trusting an
export, open the file in the viewer and check:

- **Does the header clock agree with the sample count?** `Points for Each Channel /
  Data Sampling Rate` should match the `Start Time`→`Stop Time` span. When it does not —
  and it often does not — sample index is the only reliable time base. The viewer shows
  the discrepancy in its header when it finds one.
- **How much of each ECG lead survives?** The precordial leads clip most, and they are the
  ones that carry anterior ischaemia. If V1–V4 lose a large fraction to saturation, ask
  the lab to lower the recording gain before collecting more cases; the usual cause is
  motion-driven baseline wander pushing the signal into the rail, not genuine R-wave
  amplitude.
- **Which pressure ports were live, and when.** Auto-detect in the viewer gives the live
  span. A wedge port used episodically will show mid-case gaps that are real.
- **What the `.bin` does not contain.** It is exactly `N × C × 8` bytes with nothing left
  over: no annotation stream, and no NBP, SpO2, or respiration channel. Procedure notes,
  balloon-inflation times, and NBP readings have to come from a separate case-log export
  by the recording system.
