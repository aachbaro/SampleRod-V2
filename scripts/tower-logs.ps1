# tower-logs.ps1 — voit les logs du site sur la tour, depuis Windows.
#
# Usage :
#   .\scripts\tower-logs.ps1                   # 100 dernières lignes
#   .\scripts\tower-logs.ps1 -Follow           # follow (Ctrl-C pour sortir)
#   .\scripts\tower-logs.ps1 -Tunnel           # inclut logs du tunnel Cloudflare
#   .\scripts\tower-logs.ps1 -Follow -Tunnel
#   .\scripts\tower-logs.ps1 -Since 10m        # logs des 10 dernières minutes

param(
  [switch]$Follow,
  [switch]$Tunnel,
  [string]$Since = "",
  [int]$Tail = 100,
  [string]$RemoteUser = "pascuans",
  [string]$RemoteHost = "192.168.1.14",
  [string]$RemoteDir  = "~/roadToDev/pascuans/samplerod"
)

$args = @()
if ($Follow)  { $args += "-f" }
if ($Since)   { $args += "--since"; $args += $Since }
if (-not $Follow -and -not $Since) { $args += "--tail"; $args += "$Tail" }
if ($Tunnel)  { $args += "--tunnel" }

$argsStr = $args -join " "
ssh "${RemoteUser}@${RemoteHost}" "cd $RemoteDir && ./logs.sh $argsStr"
