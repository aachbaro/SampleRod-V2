param(
    [string]$Version = $(Get-Content VERSION),
    [string]$UpdateFeed = "C:\SampleRod\updates",
    [string]$AppName = "SampleRod",
    [string]$NugetExe = "tools\nuget\nuget.exe",
    [string]$SquirrelExe = "tools\squirrel\Squirrel.exe"
)

$ErrorActionPreference = "Stop"

Write-Host "== SampleRod build_release =="
Write-Host "Version: $Version"
Write-Host "Update feed: $UpdateFeed"

if (!(Test-Path $NugetExe)) {
    throw "NuGet introuvable: $NugetExe (place nuget.exe ici)"
}
if (!(Test-Path $SquirrelExe)) {
    throw "Squirrel introuvable: $SquirrelExe (place Squirrel.exe ici)"
}

# 1) Build React UI (remote control)
Push-Location "frontend\remote_ui"
npm install
npm run build
Pop-Location

# 2) Build app (PyInstaller onedir)
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

pyinstaller --noconsole --onedir --name $AppName `
  --add-data "frontend\remote_ui\dist;frontend\remote_ui\dist" `
  app.py

# 3) Create NuGet package
if (!(Test-Path "build")) { New-Item -ItemType Directory -Path "build" | Out-Null }
$repoRoot = (Get-Location)
$nuspecPath = "build\$AppName.nuspec"
@"
<?xml version="1.0"?>
<package>
  <metadata>
    <id>$AppName</id>
    <version>$Version</version>
    <authors>$AppName</authors>
    <owners>$AppName</owners>
    <requireLicenseAcceptance>false</requireLicenseAcceptance>
    <description>$AppName</description>
  </metadata>
  <files>
    <file src="dist\$AppName\**\*" target="lib\net45" />
  </files>
</package>
"@ | Set-Content -Path $nuspecPath -Encoding UTF8

# BasePath must point to repo root so 'dist\...' resolves correctly
& $NugetExe pack $nuspecPath -BasePath $repoRoot -OutputDirectory "build"

# 4) Squirrel releasify
if (!(Test-Path $UpdateFeed)) { New-Item -ItemType Directory -Path $UpdateFeed | Out-Null }
$nupkg = "build\$AppName.$Version.nupkg"

& $SquirrelExe --releasify $nupkg --releaseDir $UpdateFeed

Write-Host "OK -> Releases dans $UpdateFeed"
