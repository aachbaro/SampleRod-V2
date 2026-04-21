# deploy.ps1 — déclenche un deploy du site sur la tour depuis Windows.
#
# Pousse la branche actuelle puis exécute ./deploy.sh côté tour.
#
# Usage :
#   .\scripts\deploy.ps1              # push branche + deploy sur la tour
#   .\scripts\deploy.ps1 -WithTunnel  # inclut le tunnel Cloudflare
#   .\scripts\deploy.ps1 -SkipPush    # deploy sans push (si déjà à jour)
#   .\scripts\deploy.ps1 -Branch main # force une branche spécifique

param(
  [string]$Branch = "",
  [switch]$WithTunnel,
  [switch]$SkipPush,
  [string]$RemoteUser = "pascuans",
  [string]$RemoteHost = "192.168.1.14",
  [string]$RemoteDir  = "~/roadToDev/pascuans/samplerod"
)

$ErrorActionPreference = "Stop"

if (-not $Branch) {
  $Branch = (git branch --show-current).Trim()
}

if (-not $SkipPush) {
  Write-Host "-- push $Branch vers origin --" -ForegroundColor Cyan
  git push origin $Branch
} else {
  Write-Host "-- push skipped --" -ForegroundColor Yellow
}

$deployArgs = @($Branch)
if ($WithTunnel) { $deployArgs += "--with-tunnel" }
$argsStr = $deployArgs -join " "

Write-Host "-- deploy sur ${RemoteHost} --" -ForegroundColor Cyan
ssh "${RemoteUser}@${RemoteHost}" "cd $RemoteDir && ./deploy.sh $argsStr"
