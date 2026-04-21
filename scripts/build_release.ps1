param(
    [string]$Version = $(Get-Content VERSION),
    [string]$UpdateFeed = "C:\SampleRod\updates",
    [string]$AppName = "SampleRod",
    [string]$SpecPath = "SampleRod.spec",
    [string]$NugetExe = "tools\nuget\nuget.exe",
    [string]$SquirrelExe = "tools\squirrel\Squirrel.exe"
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
Assert-LastExitCode "npm install"
npm run build
Assert-LastExitCode "npm run build"
Pop-Location

# 2) Build app (PyInstaller onedir)
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

if (Test-Path $SpecPath) {
    pyinstaller --clean --noconfirm $SpecPath
} else {
    pyinstaller --noconsole --onedir --name $AppName `
      --add-data "frontend\remote_ui\dist;frontend\remote_ui\dist" `
      app.py
}
Assert-LastExitCode "pyinstaller"

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
Assert-LastExitCode "nuget pack"

# 4) Squirrel releasify
if (!(Test-Path $UpdateFeed)) { New-Item -ItemType Directory -Path $UpdateFeed | Out-Null }
$nupkg = "build\$AppName.$Version.nupkg"

& $SquirrelExe --releasify $nupkg --releaseDir $UpdateFeed
Assert-LastExitCode "Squirrel releasify"

$expectedFiles = @(
    (Join-Path $UpdateFeed "Setup.exe"),
    (Join-Path $UpdateFeed "RELEASES"),
    (Join-Path $UpdateFeed "$AppName-$Version-full.nupkg")
)
foreach ($expected in $expectedFiles) {
    if (!(Test-Path $expected)) {
        throw "Artefact attendu introuvable apres releasify: $expected"
    }
}

$releasesManifest = Get-Content (Join-Path $UpdateFeed "RELEASES") -Raw
$expectedPackageName = "$AppName-$Version-full.nupkg"
if ($releasesManifest -notmatch [regex]::Escape($expectedPackageName)) {
    throw "Le manifeste RELEASES ne reference pas $expectedPackageName."
}

Write-Host "OK -> Releases dans $UpdateFeed"
