# sync.ps1 — pull safe + status du repo local.
#
# À lancer en début de session, avant de commencer à coder.
#
# Usage :
#   .\scripts\sync.ps1

$ErrorActionPreference = "Stop"

$branch = (git branch --show-current).Trim()
Write-Host "-- sync $branch --" -ForegroundColor Cyan

git fetch origin
$behind = (git rev-list --count "HEAD..origin/$branch" 2>$null)
$ahead  = (git rev-list --count "origin/$branch..HEAD" 2>$null)

Write-Host "local  : ahead $ahead, behind $behind vs origin/$branch"

$dirty = (git status --porcelain)
if ($dirty) {
  Write-Host "`n⚠ modifications non commitées :" -ForegroundColor Yellow
  git status --short
  Write-Host "`nCommit ou stash avant de pull." -ForegroundColor Yellow
  exit 1
}

if ([int]$behind -gt 0) {
  git pull --ff-only origin $branch
  Write-Host "✓ pull OK" -ForegroundColor Green
} else {
  Write-Host "✓ déjà à jour" -ForegroundColor Green
}
