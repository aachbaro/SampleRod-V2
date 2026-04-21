# cp.ps1 — commit rapide + push.
#
# Équivalent de `git add -A && git commit -m "..." && git push`.
# Rejette si tu es sur main (par sécurité).
#
# Usage :
#   .\scripts\cp.ps1 "feat(waveform): zoom horizontal au scroll"
#   .\scripts\cp.ps1 "fix: bug lecture loop" -NoPush   # commit sans push

param(
  [Parameter(Mandatory = $true)][string]$Message,
  [switch]$NoPush,
  [switch]$AllowMain
)

$ErrorActionPreference = "Stop"

$branch = (git branch --show-current).Trim()

if ($branch -eq "main" -and -not $AllowMain) {
  Write-Host "✗ tu es sur main. Utilise -AllowMain pour passer outre." -ForegroundColor Red
  exit 1
}

$changes = (git status --porcelain)
if (-not $changes) {
  Write-Host "rien à commiter." -ForegroundColor Yellow
  exit 0
}

Write-Host "-- add --" -ForegroundColor Cyan
git add -A
Write-Host "-- commit --" -ForegroundColor Cyan
git commit -m $Message

if (-not $NoPush) {
  Write-Host "-- push --" -ForegroundColor Cyan
  git push origin $branch
  Write-Host "✓ pushed $branch" -ForegroundColor Green
} else {
  Write-Host "✓ commit ok (push skipped)" -ForegroundColor Green
}
