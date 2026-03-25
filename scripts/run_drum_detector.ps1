param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DetectorArgs
)

python -m prototypes.drum_detector.cli @DetectorArgs
