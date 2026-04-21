# tower-status.ps1 — état du site + containers + releases sur la tour, depuis Windows.
#
# Usage :
#   .\scripts\tower-status.ps1

param(
  [string]$RemoteUser = "pascuans",
  [string]$RemoteHost = "192.168.1.14",
  [string]$RemoteDir  = "~/roadToDev/pascuans/samplerod"
)

ssh "${RemoteUser}@${RemoteHost}" "cd $RemoteDir && ./status.sh"
