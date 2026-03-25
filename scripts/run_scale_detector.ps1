param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DetectorArgs
)

python -m prototypes.scale_detector.cli @DetectorArgs
