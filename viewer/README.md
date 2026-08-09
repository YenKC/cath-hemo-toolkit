# Cath Waveform Viewer

A single HTML file. Double-click `cath_viewer.html`, pick a case's **`.inf` and `.bin`
together**, and it plays back like the Mac-Lab real-time panel.

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
| Readout panel | drag its top edge to resize |
| Study range | Set In / Set Out (keys **I** / **O**), draggable handles, Auto-detect, multiple segments |
| Cleaning | see below — every control has a tooltip |
| Export | window, any set of segments (chooser dialog), or whole study; cleaned or raw |

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

Every cell reserves room for its widest plausible value (`HR` 3 characters, a pressure
`150/100/130` 11 characters), so the row never reflows as the numbers change. The track
bar sits **above** the panel and spans only the waveform column, so its position and width
never move — dragging the position indicator always behaves the same.

Slots for `SpO2`, `NBP`, `RR` and `Temp` are always present and sit empty when the
recording has no such channel, so a case that does carry them lands in the same layout.

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
  the median ST shift from cleaning is −1.7 µV and no beat moves by more than 100 µV.
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
- Requires a current Chrome, Edge, Safari, or Firefox.
