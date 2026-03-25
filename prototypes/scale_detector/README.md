# Scale Detector Prototype

This prototype is intentionally isolated from the main `samplerod` runtime.

That is the cleanest option right now because:

- we can iterate on the detection logic without launching the full desktop app
- we avoid coupling an unstable algorithm to the existing UI and DB too early
- the core logic is already packaged so we can move it into a real service later

## Layout

- `analyzer.py`: pure analysis logic using `librosa`
- `cli.py`: standalone launcher for a file or a folder
- `ui.py`: mini UI standalone for picking a sample and testing quickly

## Usage

Install dependencies first if needed:

```powershell
python -m pip install -r requirements.txt
```

From the `samplerod` folder:

```powershell
python -m prototypes.scale_detector.cli .\path\to\sample.wav
```

Analyze a folder:

```powershell
python -m prototypes.scale_detector.cli .\samples --recursive
```

Structured JSON output:

```powershell
python -m prototypes.scale_detector.cli .\samples\loop.wav --json
```

Shortcut script:

```powershell
.\scripts\run_scale_detector.ps1 .\samples --recursive
```

Launch the mini UI:

```powershell
python -m prototypes.scale_detector.ui
```

Or:

```powershell
.\scripts\run_scale_detector_ui.ps1
```

## Current behavior

- lets you preview the selected sample directly in the mini UI
- embeds the SampleRod waveform editor when its UI deps are available
- detects note segments and places markers on the waveform
- labels each segment as `mono` or `poly` and lists active notes for polyphonic parts
- loads audio with `librosa`
- isolates the harmonic component
- builds a chroma profile
- ranks common tonal templates
- returns either a `note` guess or a `scale` guess depending on how many pitch classes are active

## Important limits

- a one-shot note, a chord stab, or a short loop can be musically ambiguous
- relative keys can still be confused if the sample does not establish a tonal center
- this is good enough for prototyping and dataset tagging, not yet for silent auto-tagging in the main app

## Suggested next integration step

When the ranking feels stable enough:

1. move `analyzer.py` into a dedicated backend service
2. add a manual "Detect key/scale" action in the Sample UI
3. only after that, think about persistence in DB / settings
