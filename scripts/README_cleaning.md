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
| `<stem>_{clean,raw}_trend.csv` | one per second | HR, per-second pressure mean/min/max, per-channel validity |
| `<stem>_{clean,raw}_events.csv` | one per log event | with `--log`: the case-log table, joinable on `t_sec` |
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
| `--trend-only` | off | skip the full-rate CSV, which is large |
| `--log PATH` | off | fold the case log into every row (see below) |
| `--log-anchor auto\|header\|first` | auto | what pins the log clock to `t_sec` 0 |
| `--log-offset SEC` | 0 | shift every event on top of the anchor |
| `--peri-window SEC` | 120 | how far either side of an inflation `peri_t` is filled |
| `--log-fit` | off | try to align the log by matching charted HR to measured HR |

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
3. *Void stretches where the transducer is not live.* Most of what this removes sits before
   the case starts and after it ends. A wedge port is genuinely intermittent — it gets used
   episodically — so expect gaps mid-case on that channel; those are real, not a bug.

   This test asks **"is a transducer connected and reading?"** and nothing else. It is not
   a normality filter, and keeping the two apart matters: an earlier version required a
   median above 30 mmHg of *every* pressure channel, which is true of an aortic line and
   false of every right atrium ever recorded — it deleted **99.5%** of a real RA trace,
   including the RA rise during a tamponade that was the most diagnostic thing in the case.

   So the bands (`LIVE_RULES`, matched by pattern so `AO2`/`FA`/`ART` need no entry) are
   sized to **pathology, not textbook ranges** — severe TR drives RA into the 30s, acute MR
   drives wedge v waves past 50, severe PAH puts PA systolic near 100, critical AS puts LV
   over 250. An unrecognised label gets the widest band of all, because silently deleting a
   channel nobody taught the script about is the worse failure.

   Judged per 10 s block, a block is live when its median is in range **and** it is either
   pulsatile enough **or** flat at a level only a connected line reaches. That last clause
   exists for **ECMO and bypass**: a non-pulsatile arterial trace at a pulse pressure of
   2–3 mmHg is real signal, and pulsatility alone cannot tell it from a flushed or
   disconnected line. Level can — measured on the real cases, the scattered flat blocks sit
   at ~10 mmHg (transducer off) or above 180 mmHg (the 300 mmHg flush bag), while perfusing
   flat support sits between. Override any channel with `Config.live_rules`.

**ECG channels**

1. *Void ADC saturation.* Full scale is ±5 mV at 12 bits (LSB 2.44 µV). The threshold is
   derived from the data (0.998 × observed full scale) and only applied if the extreme
   value repeats more than 100 times, so a recording without clipping is left alone.
   Saturated runs are padded by 12 ms either side.
2. *Remove baseline wander* with a two-stage median (200 ms then 600 ms) estimated only
   from unsaturated samples, then subtracted. The 200 ms window is longer than any QRS,
   so the estimate follows the baseline and not the beat.

## Joining the case log to the signal — `--log`

The `.bin` carries no annotation stream, so on its own it cannot say when a balloon went
up. `--log` reads the Mac-Lab case log and writes its events **into the same rows as the
signal**, so a statistics package opens one file instead of joining two.

Sixteen columns are appended to both the full-rate and the trend CSV:

| column | meaning |
|---|---|
| `event`, `event_kind` | the event text landing in this row, and its category. Sparse — most rows are empty |
| `infl` | 1 while a balloon or stent is up, else 0 |
| `infl_n`, `infl_target`, `infl_atm` | which inflation, which vessel, at how many atmospheres |
| `infl_t` | seconds since that inflation started |
| `peri_n`, `peri_t` | nearest inflation, and **signed seconds to its start** |
| `log_hr`, `log_spo2`, `log_rr`, `log_nbp_{sys,dia,mean}` | the last charted values, carried forward |
| `log_age_s` | how old those charted values are, so stale ones can be dropped |

An inflation is an **interval**, not an instant, which is why `infl` is a state rather than
a marker: the distinction between "a balloon went up at 52 s" and "these 18 seconds were
recorded with the artery occluded" is the whole analysis.

`peri_t` is the column to group by. Every inflation aligned on `peri_t == 0` turns
"does the vital sign move around balloon inflation" into an average over inflations rather
than a case-by-case eyeball:

```python
d = pd.read_csv('CASE_clean_trend.csv')
d[d.peri_t.between(-60, 60)].groupby(d.peri_t.round())['HR_bpm'].mean()
```

The viewer emits the identical columns, in the identical order, so the two are
interchangeable; `viewer/cath_viewer.html` and `scripts/caselog.py` are two implementations
of one spec and must be changed together.

### Aligning the log is the weak link — check it per case

Both clocks are naive local time and they do not always agree. Of the two real cases this
was built against, one matched its `.inf` `Start Time` **to the second** and the other was
out by **5 h 24 min**. `auto` scores both anchorings by how many events land on the
recording and picks the better, saying so in the QC file.

`--log-fit` goes further and tries to align on the data itself, matching the HR the nurse
charted against the HR measured from the ECG. **On these two cases it does not work, and
says so rather than guessing.** HR is charted often but barely moves — every offset across
a ~1500 s span fits within 1 bpm — while AO moves plenty but is charted only twice per
case. Fitting needs a quantity that is both frequently recorded and genuinely variable, and
neither qualifies. The guard refuses any fit whose minimum is flat over 120 s.

### The one check a clock cannot fool

A pressure trace cannot begin before the artery that produced it was punctured. Every
export with `--log` therefore compares when the arterial channel actually goes live
(first second that is live and stays live 30 s) against the first logged access event:

- on the clock-verified case the trace starts **+131 s** after the logged puncture —
  puncture, sheath, catheter, zeroed transducer, which is exactly right;
- on the other case it started **966 s before** access was logged, which is impossible,
  and proved the anchor wrong by at least that much. Nothing clock-based had caught it.

The QC file states the hard lower bound and, allowing the same 131 s puncture-to-live
delay, suggests the `--log-offset` that fixes it. Applying it made the check read `+131 s`
and independently pulled the HR fit's preferred offset from +748 s down to +55 s. It moved
mean AO during inflation from 107.9 to 119.2 mmHg — alignment is not cosmetic.

Treat the suggestion as an estimate, not a measurement: it assumes no arterial line was
already in place before the case, which for an emergency it might have been.

So alignment rests on the clock, and the clock has to be fixed upstream. **Ask the lab why
a header `Start Time` disagrees with its own case log** — that is a recording-system
question, not something the data can answer. Until then, treat `t_sec` as truth and the
event times on a mis-anchored case as carrying minutes of uncertainty; the QC file states
the bound implied by the two spans.

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
| ST (J+60 vs PR) shift from cleaning | median **−1.5 µV**, IQR [−20.9, +6.4] |
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
