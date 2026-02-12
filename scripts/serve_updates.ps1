param(
    [string]$UpdateDir = "C:\SampleRod\updates",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $UpdateDir)) {
    throw "Dossier introuvable: $UpdateDir"
}

Write-Host "== Serveur updates (Squirrel) =="
Write-Host "Dossier: $UpdateDir"
Write-Host "Port: $Port"
Write-Host ""
Write-Host "Feed URL (ex): http://<IP_HOTE>:$Port/"
Write-Host "Pour trouver l'IP: ipconfig"
Write-Host ""

Push-Location $UpdateDir
python -m http.server $Port --bind 0.0.0.0
Pop-Location
