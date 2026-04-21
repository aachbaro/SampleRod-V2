#
# publish_release.ps1
#
# 1. Build the current VERSION of SampleRod into a Squirrel bundle
#    (via scripts/build_release.ps1).
# 2. scp it to the Linux tour under /srv/samplerod/releases/<version>/.
# 3. Call the site's /api/admin/publish endpoint to flip `current -> <version>`.
#
# Typical invocation, after bumping the VERSION file:
#   $env:SAMPLEROD_ADMIN_TOKEN = "<token from site .env.prod>"
#   .\scripts\publish_release.ps1
#
# Overrides:
#   .\scripts\publish_release.ps1 -Version 0.1.4 -Notes "fix waveform click"
#   .\scripts\publish_release.ps1 -SkipBuild   # re-push without rebuilding
#   .\scripts\publish_release.ps1 -SkipUpload  # build only
#
param(
  [string]$Version    = $(Get-Content VERSION),
  [string]$UpdateFeed = "C:\SampleRod\updates",
  [string]$Notes      = "",
  [string]$RemoteUser = "pascuans",
  [string]$RemoteHost = "192.168.1.14",
  [string]$RemoteDir  = "/srv/samplerod/releases",
  [string]$SiteUrl    = "https://samplerod.pascuans.dev",
  [switch]$SkipBuild,
  [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
  $PSNativeCommandUseErrorActionPreference = $true
}

function Assert-LastExitCode([string]$Label) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Label a echoue avec le code de sortie $LASTEXITCODE."
  }
}

Write-Host "== SampleRod publish_release =="
Write-Host "Version     : $Version"
Write-Host "Local feed  : $UpdateFeed"
Write-Host "Remote      : ${RemoteUser}@${RemoteHost}:${RemoteDir}/${Version}/"
Write-Host "Site        : $SiteUrl"

# 1) Build
if (-not $SkipBuild) {
  Write-Host ""
  Write-Host "-- step 1/3 : build Squirrel bundle --"
  & .\scripts\build_release.ps1 -Version $Version -UpdateFeed $UpdateFeed
} else {
  Write-Host "-- step 1/3 : build SKIPPED --"
}

# 2) rsync / scp
if (-not $SkipUpload) {
  Write-Host ""
  Write-Host "-- step 2/3 : upload to tour --"
  if (-not (Test-Path $UpdateFeed)) {
    throw "Local feed not found: $UpdateFeed"
  }
  $required = @(
    "RELEASES",
    "Setup.exe",
    "SampleRod-$Version-full.nupkg"
  )
  foreach ($f in $required) {
    if (-not (Test-Path (Join-Path $UpdateFeed $f))) {
      throw "Missing $f in $UpdateFeed — rebuild first."
    }
  }

  $releasesManifest = Get-Content (Join-Path $UpdateFeed "RELEASES") -Raw
  if ($releasesManifest -notmatch [regex]::Escape("SampleRod-$Version-full.nupkg")) {
    throw "RELEASES ne reference pas la version attendue $Version."
  }

  ssh "${RemoteUser}@${RemoteHost}" "mkdir -p ${RemoteDir}/${Version}"
  Assert-LastExitCode "ssh mkdir"
  # Push every file in the update feed. scp will transfer RELEASES, *.nupkg,
  # and Setup.exe — everything Squirrel knows how to consume.
  scp -r "${UpdateFeed}\*" "${RemoteUser}@${RemoteHost}:${RemoteDir}/${Version}/"
  Assert-LastExitCode "scp upload"
} else {
  Write-Host "-- step 2/3 : upload SKIPPED --"
}

# 3) Flip current/ via admin API
Write-Host ""
Write-Host "-- step 3/3 : publish via admin API --"

$token = $env:SAMPLEROD_ADMIN_TOKEN
if (-not $token) {
  throw "SAMPLEROD_ADMIN_TOKEN env var not set. Get it from the site's .env.prod."
}

$body = @{ version = $Version }
if ($Notes) { $body.notes = $Notes }
$json = $body | ConvertTo-Json

try {
  $resp = Invoke-RestMethod `
    -Uri "${SiteUrl}/api/admin/publish" `
    -Method Post `
    -Headers @{ Authorization = "Bearer $token" } `
    -ContentType "application/json" `
    -Body $json
  Write-Host "publish OK : $($resp | ConvertTo-Json -Compress)"
} catch {
  Write-Host "publish FAILED: $($_.Exception.Message)" -ForegroundColor Red
  if ($_.ErrorDetails.Message) {
    Write-Host "server said: $($_.ErrorDetails.Message)" -ForegroundColor Red
  }
  throw
}

Write-Host ""
Write-Host "== done -> version $Version is now current on $SiteUrl =="
