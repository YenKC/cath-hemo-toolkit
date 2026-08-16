# Cath Waveform Viewer

A single HTML file. Double-click `cath_viewer.html`, **drag a case folder onto it**, and it
plays back like the Mac-Lab real-time panel — the `.inf`, the `.bin` and the **case log**
inside are found for you, so every balloon inflation, drug and NBP reading lands on the
timeline beside the waveform.

## Opening a case

| you have | do this |
|---|---|
| a case folder | drag it onto the window, or **Open folder** |
| a folder of several cases | same — a chooser lists each one with its channel count, length, and whether a log was found |
| loose files | **Open files** and select the `.inf` and `.bin` **together** (plus the log) |
| a log for a case already open | **+ case log** |

**Why you cannot just pick the `.bin`.** A browser hands a page a `File` — a name and some
bytes. There is no path and no way to look at the folder around it; that is a deliberate
security boundary, not something the page can work around. Handing over the *folder* is the
version of "find the rest for me" that actually works, which is why it is the primary path
here. Pick a `.bin` on its own and the viewer says so rather than failing vaguely.

**To give this to a colleague, send them this one file.** No install, no Python, no
server, no build step — they open it and load their own `.inf`/`.bin`.

## Nothing is uploaded

The page reads the `.bin` straight off the local disk through the browser's file API, a
few seconds of signal at a time. **No patient data leaves the machine** — there is no
network code in the file at all. That is also why it isn't hosted anywhere.

A **hide identifiers** toggle in the header blanks the patient name for screenshots,
teaching, and screen sharing.

## Why it opens a 500 MB file instantly

It never loads the whole recording. A 10 s window of 14 channels at 240 Hz is 2,400
samples per channel — a few hundred kilobytes, fetched as one byte-range slice. **Opening
is independent of length**, and jumping to the last hour of a recording costs exactly what
the first hour costs. A multi-hundred-megabyte file appears immediately.

## It checks that the `.bin` belongs to the `.inf`

`points × channels × 8` has to equal the file size exactly, so a mismatch is caught before
anything is drawn rather than producing plausible-looking nonsense. **When more than one
`.bin` is in view, the viewer picks the one the header actually describes** — by size, not
by filename. If that turns out to be a different file from the one sharing the stem, it
opens the right one and says the two look swapped. Two of the first three real cases handed
over were filed that way, so open the parent folder and the mix-up resolves itself.

## Channels come from the file, not from a template

Nothing assumes 12-lead + AO + PCW. The count, names, and order are read from the
`.inf`, and each channel's **type** is auto-detected — standard lead names settle the
ECG ones, and everything else is decided from the data, because the ADC step differs by
an order of magnitude (ECG ≈ 0.0024 mV vs pressure 0.2 mmHg). Override any channel with
the ECG / Press / Other dropdown next to it.

Two pressure lines of the same kind are handled: a case with **AO + AO2** (dual access
for a CTO) or **AO + LV** (for AS) gets a distinct colour per trace — conventional
first (arterial red, wedge blue, LV magenta, right heart yellow), then the palette — and
**one numeric readout per channel** in the footer. Pulsatile channels show
systolic/diastolic/mean; low-pressure ones show mean only, decided per window from the
actual pulse pressure.

## Controls

| control | notes |
|---|---|
| Window length | 5 / 10 / 15 / 20 / 30 / 60 s |
| Play speed | 1× real time up to 300×. Actual rate is read/render bound — 60× measures ≈54× |
| Navigation | scrub bar, `Go to (s)`, prev/next, play, arrow keys (shift = 6 windows), space |
| Channels | per channel: show/hide, type override, full-scale range (or wheel over the lane) |
| Panes | bold draggable line between ECG and pressure |
| Pressure layout | one lane each (default, so wedge detail survives) or overlaid on the arterial channel's axis for gradients |
| Readout panel | drag its top edge to resize; values are window aggregates |
| Time cursor | hover the chart for per-trace values at one instant; click to pin |
| Study range | Set In / Set Out (keys **I** / **O**), draggable handles, Auto-detect, multiple segments |
| Case log | filter chips, search, click to jump, **N** / **P** step through shown events, anchor + nudge, drag the panel edge to resize |
| Timeline track | drag its top edge to make it taller; event bars grow with it and gain labels |
| Text size | one control in the log panel resizes the event rows and the chart annotations together |
| Cleaning | see below — every control has a tooltip |
| Export | window, any set of segments (chooser dialog), or whole study; cleaned or raw; plus the event table |

## Giving ECG or pressure more room

The ECG pane and the pressure pane are separated by a **bold draggable line** on the
chart. Grab it and pull. When a low wedge and a high arterial line are on screen together,
pull it up so the pressure pane gets the space.

## Changing a lane's scale

**Scroll the wheel over any lane** — ECG or pressure. That is the only gesture; the number
box in the channel list follows, and typing in the box works too.

| type | range | step |
|---|---|---|
| ECG | 0.1 – 10.0 mV | 0.1 |
| pressure | -20 – 500 mmHg | 5 |

The baseline of a pressure lane stays at **0**, with a little room drawn below it so
negative wedge dips stay visible instead of being clipped at the bottom.

**The lane scale only changes the picture.** A trace that runs off the top of its lane is
still fully present in the exported CSV. What *does* cut data is the **Lower/Upper limit**
under *Pressure cleaning* — samples outside that window are voided in the clean export
(they survive untouched in a raw export). Two different controls, easy to confuse.

With **Overlay pressures on one axis**, the shared axis is the **arterial channel's**
scale — the axis label says which one — so AO and LV can be read against each other for a
gradient. The wheel over the overlaid pane adjusts that reference channel.

## The readout panel

**Drag its top edge** to make it taller or shorter; the values scale with it.

**Every number in this panel is an aggregate over the whole visible window**, not a
reading at one instant — a 10 s window's AO `146/87/112` is its 98th percentile, 2nd
percentile and mean across those 10 seconds. That is the right summary for orientation and
the wrong one for checking a logged value against the trace, so the chart carries a **time
cursor** for the second job:

- **hover the chart** and a line follows the pointer, marking each visible trace with a dot
  and its value *at that instant*, with the exact time and wall clock at the foot of the plot;
- **click to pin it**, so a value can be read without holding the mouse still; click again
  to release;
- the readout beside the scrub bar says which you are looking at — `window 0:21:51–0:22:01`
  when there is no cursor, `pinned 0:21:56  8:33:30 AM` when there is.

That is how a logged reading gets checked against the recording: click the event in the log
panel to jump there, pin the cursor on it, and compare. On the clock-verified case the log's
`AO : 149/93/118` at 8:33:30 AM lands on a trace reading 146/87 — which is what agreement
looks like.

Every cell reserves room for its widest plausible value (`HR` 3 characters, a pressure
`150/100/130` 11 characters), so the row never reflows as the numbers change. The track
bar sits **above** the panel and spans only the waveform column, so its position and width
never move — dragging the position indicator always behaves the same.

Slots for `SpO2`, `NBP`, `RR` and `Temp` are always present and sit empty when the
recording has no such channel, so a case that does carry them lands in the same layout.
When there is no channel but a **case log** is loaded, the slot is filled from the most
recent charted value instead, underlined and captioned `log 2m ago`. That caption is the
point: an NBP from the log was measured once, minutes ago, by a cuff — it is not the
arterial line beside it, and the two must never be read as the same kind of number.

**SpO2 is light blue** so it can be picked out of the row at a glance without reading
labels. Each readout's colour is set inline from a single `col` field in the `MONITOR`
table, so changing one is a one-line edit — and note that a stylesheet rule targeting `.v`
cannot override it, which is exactly the trap that made an earlier attempt at this a no-op.

## The case log

The `.bin` has no annotation stream — the file size is exactly `N × C × 8` with nothing
left over — so the recording alone cannot tell you when a balloon went up. That lives in
the Mac-Lab case-log document, and loading it is what turns the waveform into something
you can reason about.

Select it together with the `.inf`/`.bin`, drop it on the window, or use **+ case log** to
attach one to a case that is already open. `.docx`, `.odt` and plain `.txt` all work.
Word and ODF files are ZIP containers, and the viewer unpacks them itself with the
browser's built-in decompressor — **still no library and still no network**, which is what
keeps opening a document full of PHI acceptable.

The parser wants one thing: a line holding **only a time**, followed by the event text,
followed by any comment lines. Everything before the first timestamp is treated as the
patient-information block and is never displayed.

### What it pulls out

Events are sorted into categories you can toggle, each with its own colour:

| category | examples |
|---|---|
| `inflation` | balloon, cutting balloon, stent — **duration, atmospheres and target vessel** are parsed out |
| `pressure` | `AO : 115/55/72, HR = 76`, wedge and PA readings, snapshots |
| `vitals` | `SpO2 98%; HR 81 bpm; 91/69/74 NBP; RR 61/min` |
| `med` | heparin, NTG, and anything with a unit/mcg/mg dose |
| `lab` | ACT, saturations, contrast volume |
| `procedure` | access, time out, cannulation, anything prefixed `Procedure:` |
| `device` / `hardware` | thrombectomy, IVUS, pullback; and the supply lines (`NC Trek 4.0mm x 12mm … As:Abbott`) |

Categories are a table in the source, not a chain of conditionals, so a lab that words
its log differently is a data edit rather than a rewrite.

### On the timeline

An inflation has a **duration**, so it is drawn as an interval, not a pin: a solid strip
along the top of the chart spanning it, faint tint beneath, and a boundary line at each
end. Sitting inside an inflation longer than the window, the label pins to the left edge
prefixed `<` so you can still tell which one. Everything else is a dashed vertical line
with a label.

The same events tick along the scrub track, and **dragging the track's top edge makes it
taller** — the bars grow with it, and once one is wide enough to hold text it gets its
label, turning the strip into a gantt of the whole case instead of a row of anonymous
ticks. **Text size (px)** in the log panel scales the event rows and the chart annotations
together, from 9 up to 22.

Click any event to jump to it. **N** and **P** step through the events *currently shown*,
so filtering to `inflation` and holding **N** walks the case balloon to balloon — which is
the motion the peri-balloon analysis is actually made of. The search box filters on text,
so `LAD` narrows to one vessel.

### Anchoring the log to the recording

The log is wall-clock; the waveform is sample index. **Anchor** picks what pins them
together — the `.inf` `Start Time`, or the first log event at 0 s — and **Nudge** shifts
by seconds on top.

The viewer chooses for you by scoring each anchor on how much of the log actually lands on
the recording, then says so when the answer is unflattering. This is not hypothetical: of
the two cases this was built against, one matched its header **to the second**, and the
other was off by 5h24m, which would have put every event past the end of the file. That
case now loads with a warning and the working anchor already selected. A header time that
disagrees with its own log is a reason to distrust the header, not the log — sample index
stays the only time base you can lean on.

### The events go into the waveform CSV too

With a log loaded, **every CSV export gains 16 event columns** alongside the signal, so a
statistics package reads one file rather than joining two: `event`/`event_kind`, the
inflation state (`infl`, `infl_n`, `infl_target`, `infl_atm`, `infl_t`), the alignment pair
(`peri_n`, `peri_t` — signed seconds to the nearest inflation, the column to group by), and
the last charted vitals carried forward (`log_hr`, `log_spo2`, `log_rr`,
`log_nbp_{sys,dia,mean}`, `log_age_s`).

`scripts/clean_export.py --log <file>` writes exactly the same columns in the same order —
the generated command in the Export panel already includes `--log` and the anchor — so a
window checked on screen and a whole study run in batch are interchangeable. The two are
separate implementations of one spec and are tested against each other byte-for-byte.

**Events → CSV** still writes the standalone table — `t_sec`, both clocks, category,
duration, atm, target vessel, pressures, HR/SpO2/RR/NBP, text — for joining on `t_sec`.

**hide identifiers** blanks the log's filename along with the patient name; on these
exports the filename *is* the MRN.

## Trimming the dead time

A recording starts before the patient is on the table and ends after everything is
disconnected, so both ends are meaningless signal. Mark the real study instead of
exporting all of it:

- **Set In / Set Out** (or the **I** and **O** keys) mark the current position. The span
  is drawn on the track with a **handle at each end that you can drag directly**, and the
  **waveform display follows the handle as you drag it**, so you can see exactly where you
  are cutting. Dragging In past Out simply swaps them.
- **Auto-detect** finds the first and last moment any pressure transducer is live. It
  samples the whole recording in about a second, however long the recording is.
- **+ segment** adds another In/Out pair when a case needs to be split into parts. Each
  segment exports separately; click a segment's number to make it active, its time range
  to jump there, or **×** to delete it.
- **Clear this** empties only the active segment's marks; **Clear all** discards every
  segment.

Auto-detect is a starting point, not a verdict — check the edges and adjust.

## Exporting several segments at once

**Segments → CSV…** opens a chooser rather than exporting just the active one. It lists
every *complete* segment (an unfinished In-without-Out is left out), all ticked by default,
with each one's duration and row count, and a running total in bytes.

**Combine into a single CSV file** decides the shape of the output:

- *unchecked* — one file per segment, named `<stem>_seg2_4200-9600s_clean.csv`. Chrome and
  Edge ask for a **destination folder once** and stream every file into it; other browsers
  fall back to one download per segment.
- *checked* — one file with a **`segment` column first**, so rows stay attributable once
  the ranges are concatenated. Segment boundaries also show as a jump in `t_sec`, which
  stays absolute from the start of the recording throughout.

`Segments (raw) → CSV…` is the same dialog against the untouched signal.

## What the cleaning controls do

Every control has a hover tooltip. The ones worth spelling out:

- **Ringdown pad (s)** — a flush or contrast injection spikes the pressure line, and the
  transducer keeps *oscillating* after the spike itself is back in range. Voiding only
  the out-of-range samples leaves that decaying tail behind, so this also voids the given
  number of seconds either side of every artefact sample.
- **Mask saturation** — when the ECG amplifier is driven past its range, the ADC stops
  following the signal and pins at its most extreme code. Those samples carry no
  information, but they *look* like clean flat data. The danger is specific: if the PR
  baseline and the J-point of a beat are both pinned, they differ by exactly zero, and an
  ST algorithm reports a confident, perfectly normal ST segment for a beat it cannot
  actually see. This voids those samples so they read as missing rather than as normal.
  The precordial leads are the usual casualties, and they are the ones that matter for
  LAD/LM — so check how much of V1–V4 survives before trusting an anterior ST endpoint.
  The bundled sample voids 3.4% of V2 and 1.2% of V4; a real recording with poor electrode
  contact can lose several times that.
- **Threshold (mV)** — measured from your file when it loads, not hardcoded. It reads
just under 5 mV on a ±5 mV recorder, because the rail is not a round number: a ±5 mV
  range digitised at 12 bits has a most-extreme code of 2047, i.e. 2047 × 2.4414 µV =
  **4.9988 mV**. A threshold of 5.00 would never match a single sample. The viewer samples
  the record and confirms the extreme value *repeats* — thousands of times where there is a
  rail, once for a tall R wave — then sets the threshold just inside it. A recorder at a
  different gain gets a different number automatically.
- **Pad (s)** (ECG) — same idea for saturation: the samples entering and leaving the rail
  are already distorted, so a small margin around each saturated run goes too.
- **Remove wander** — estimates the slowly drifting baseline (breathing, electrode
  motion) with a running median and subtracts it, so beats sit on a flat line. It is
  ST-preserving, which matters because ST is measured beat-relative: on the bundled sample
  the median ST shift from cleaning is −1.5 µV and no beat moves by more than 100 µV.
  Reproduce with `python scripts/validate_cleaning.py`.
- **Median window (s)** — the width of that running median. It **must stay longer than a
  QRS** (≈0.1 s). At 0.2 s the median steps over the beat and follows the baseline; drop
  it near 0.1 s and the estimate starts tracking the QRS itself and flattens the R wave.

## Tune here, batch there

The Export panel builds the matching `clean_export.py` command for the current settings —
including `--start`/`--stop` for the selected segment. Copy it, run it once, and the whole
recording is exported with exactly the parameters you just eyeballed. The viewer and the
batch script share one definition of what each setting means.

For a whole multi-hour study the Python script is considerably faster than the
in-browser export. Use the browser export for segments; use the script for everything.

## Frequency filters are off on purpose

This recorder has **no mains component** (the 60 Hz bin sits at 1.0–2.2× its neighbours,
i.e. no peak) and **no power above 40 Hz** (40–70 and 70–120 Hz each hold 0.0% of signal
power). A notch or low-pass here would remove real QRS content and nothing else. They are
exposed for future recorders that behave differently.

## Limits

- Pressure LSB is assumed to be 0.2 mmHg when unwrapping (correct for these GE exports).
- In-browser filters are one-pole forward+backward, adequate for a display preview. The
  batch script uses Butterworth `filtfilt` — trust the CSV, not the screen, for filtered
  numbers.
- Footer HR is a per-window slope detector for orientation, not a validated arrhythmia
  algorithm.
- Chrome and Edge stream exports straight to disk. Safari and Firefox lack that API and
  build the file in memory, so the viewer warns above ~400 MB — use the script instead.
- Reading `.docx`/`.odt` logs uses `DecompressionStream`, so it needs Chrome/Edge 103+,
  Safari 16.4+ or Firefox 113+. Anything older gets a plain message; export the log to
  `.txt` and load that instead. Zip64 documents are not handled.
- The log parser needs its timestamps on their own line. A log laid out some other way
  reports "no timestamped events found" rather than guessing.
- Requires a current Chrome, Edge, Safari, or Firefox.
