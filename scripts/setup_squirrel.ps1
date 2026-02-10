param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "."
$toolsDir = Join-Path $root "tools"
$nugetDir = Join-Path $toolsDir "nuget"
$squirrelDir = Join-Path $toolsDir "squirrel"

New-Item -ItemType Directory -Force -Path $nugetDir | Out-Null
New-Item -ItemType Directory -Force -Path $squirrelDir | Out-Null

function Download-File($url, $dest) {
    Write-Host "Downloading: $url"
    Invoke-WebRequest -Uri $url -OutFile $dest
}

# ---- NuGet.exe
$nugetExe = Join-Path $nugetDir "nuget.exe"
if ($Force -or !(Test-Path $nugetExe)) {
    Download-File "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" $nugetExe
}
else {
    Write-Host "NuGet deja present: $nugetExe"
}

# ---- Squirrel.exe (latest release zip or nupkg)
$squirrelExe = Join-Path $squirrelDir "Squirrel.exe"
if ($Force -or !(Test-Path $squirrelExe)) {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/Squirrel/Squirrel.Windows/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -match "Squirrel\.Windows-.*\.zip" } | Select-Object -First 1
    if (-not $asset) {
        # Fallback: prendre le .nupkg (c'est un zip) si le .zip n'existe pas
        $asset = $release.assets | Where-Object { $_.name -match "Squirrel\.Windows-.*\.nupkg" } | Select-Object -First 1
    }
    if (-not $asset) {
        # Fallback: récupère le package NuGet officiel (latest)
        $zipPath = Join-Path $env:TEMP "Squirrel.Windows.nupkg"
        Download-File "https://www.nuget.org/api/v2/package/Squirrel.Windows" $zipPath
    }
    else {
        $zipPath = Join-Path $env:TEMP $asset.name
        Download-File $asset.browser_download_url $zipPath
    }

    $extractDir = Join-Path $env:TEMP ("squirrel_" + [guid]::NewGuid().ToString("N"))
    # Expand-Archive ne supporte pas .nupkg directement -> on renomme en .zip si besoin
    $archivePath = $zipPath
    if ($zipPath.ToLower().EndsWith(".nupkg")) {
        $archivePath = $zipPath + ".zip"
        Copy-Item $zipPath $archivePath -Force
    }
    Expand-Archive -Path $archivePath -DestinationPath $extractDir -Force

    $found = Get-ChildItem -Path $extractDir -Recurse -Filter "Squirrel.exe" | Select-Object -First 1
    if (-not $found) {
        throw "Squirrel.exe introuvable dans l'archive."
    }
    # Copie tous les fichiers "tools" a cote de Squirrel.exe
    $toolRoot = $found.Directory.FullName
    Get-ChildItem -Path $toolRoot -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $squirrelDir $_.Name) -Force
    }

    # Squirrel.exe explicite (au cas ou)
    Copy-Item $found.FullName $squirrelExe -Force

    # Verifie Update.exe
    if (!(Test-Path (Join-Path $squirrelDir "Update.exe"))) {
        Write-Warning "Update.exe introuvable a cote de Squirrel.exe (releasify peut echouer)."
    }

    # Copie 7z.dll (requis par Squirrel pour packager)
    $sevenZipDll = Get-ChildItem -Path $extractDir -Recurse -Filter "7z.dll" | Select-Object -First 1
    if ($sevenZipDll) {
        Copy-Item $sevenZipDll.FullName (Join-Path $squirrelDir "7z.dll") -Force
    }
    else {
        # Fallback 1: chercher une installation locale de 7-Zip
        $possible7z = @(
            "C:\\Program Files\\7-Zip\\7z.dll",
            "C:\\Program Files (x86)\\7-Zip\\7z.dll"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1

        if ($possible7z) {
            Copy-Item $possible7z (Join-Path $squirrelDir "7z.dll") -Force
            Write-Host "7z.dll copie depuis: $possible7z"
        }
        else {
            # Fallback 2: telecharger 7-Zip 16.04 et extraire 7z.dll en local
            Write-Host "7z.dll introuvable, tentative d'installation locale 7-Zip 16.04..."
            $sevenZipUrl = "https://www.7-zip.org/a/7z1604-x64.exe"
            $sevenZipInstaller = Join-Path $env:TEMP "7z1604-x64.exe"
            $sevenZipTempDir = Join-Path $env:TEMP ("7zip_" + [guid]::NewGuid().ToString("N"))

            Download-File $sevenZipUrl $sevenZipInstaller
            New-Item -ItemType Directory -Force -Path $sevenZipTempDir | Out-Null

            # Installation silencieuse dans un dossier temporaire
            Start-Process -FilePath $sevenZipInstaller -ArgumentList "/S","/D=$sevenZipTempDir" -Wait

            $tempDll = Join-Path $sevenZipTempDir "7z.dll"
            if (Test-Path $tempDll) {
                Copy-Item $tempDll (Join-Path $squirrelDir "7z.dll") -Force
                Write-Host "7z.dll copie depuis installation temporaire."
            }
            else {
                Write-Warning "7z.dll introuvable apres installation temporaire."
            }

            Remove-Item $sevenZipInstaller -Force -ErrorAction SilentlyContinue
            Remove-Item $sevenZipTempDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    # Copie 7z.exe si present ailleurs dans l'archive
    $sevenZipExe = Get-ChildItem -Path $extractDir -Recurse -Filter "7z.exe" | Select-Object -First 1
    if ($sevenZipExe) {
        Copy-Item $sevenZipExe.FullName (Join-Path $squirrelDir "7z.exe") -Force
    }

    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    if ($archivePath -ne $zipPath) {
        Remove-Item $archivePath -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
}
else {
    Write-Host "Squirrel deja present: $squirrelExe"
}

Write-Host "OK: outils installes dans tools\\"
