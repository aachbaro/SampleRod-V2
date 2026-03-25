# Drum Detector Prototype

This prototype is intentionally isolated from the main `samplerod` runtime.

That keeps the drum / break heuristics easy to iterate on without coupling them
too early to the full desktop app.

## What it does

- detects `one_shot` vs `loop`
- estimates `drum`, `tonal`, `fx`, or `hybrid`
- ranks drum labels such as `kick`, `snare`, `closed_hat`, `open_hat`, `crash`, `tom`, `perc`
- ranks loop labels such as `break`, `drum_loop`, `top_loop`, `perc_loop`
- detects transient hits and places markers on the embedded SampleRod waveform

## Usage

Install deps first if needed:

```powershell
python -m pip install -r requirements.txt
```

CLI on one file:

```powershell
python -m prototypes.drum_detector.cli .\path\to\sample.wav
```

CLI on a folder:

```powershell
python -m prototypes.drum_detector.cli .\samples --recursive
```

JSON output:

```powershell
python -m prototypes.drum_detector.cli .\samples\break.wav --json
```

Launch the mini UI:

```powershell
python -m prototypes.drum_detector.ui
```

Or:

```powershell
.\scripts\run_drum_detector_ui.ps1
```

## Current limits

- this is heuristic, not ML-backed, so layered or very processed sounds stay ambiguous
- `snare` vs `clap` vs bright `perc` can still overlap
- `break` detection is a groove score, not a guarantee of classic breakbeat semantics
- transient markers are onset-based, not a full stem separation
