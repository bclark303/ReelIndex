param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [Parameter(Mandatory=$true)][string]$Version
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$logPath = Join-Path $env:TEMP 'ReelIndex-offline-install.log'
try { Start-Transcript -Path $logPath -Force | Out-Null } catch {}
try {
    $runtimeDir = Join-Path $InstallDir 'runtime'
    $toolsDir = Join-Path $InstallDir 'tools'
    $appDir = Join-Path $InstallDir 'app'
    $pythonExe = Join-Path $runtimeDir 'python.exe'
    $pythonwExe = Join-Path $runtimeDir 'pythonw.exe'
    $launcher = Join-Path $InstallDir 'ReelIndex.exe'
    $uninstaller = Join-Path $InstallDir 'Uninstall ReelIndex.exe'

    foreach ($required in @($pythonExe,$pythonwExe,$launcher,$uninstaller,(Join-Path $appDir 'windows_launcher.py'),(Join-Path $toolsDir 'ffprobe.exe'))) {
        if (-not (Test-Path $required)) { throw "Required bundled file is missing: $required" }
    }

    $pthFile = Get-ChildItem -Path $runtimeDir -Filter 'python*._pth' -File | Select-Object -First 1
    $stdlibZip = Get-ChildItem -Path $runtimeDir -Filter 'python*.zip' -File | Select-Object -First 1
    if ($pthFile -and $stdlibZip) {
        @($stdlibZip.Name,'.','Lib\site-packages','..\app','import site') | Set-Content -Path $pthFile.FullName -Encoding ASCII
    }

    & $pythonExe -c "import fastapi, uvicorn, sqlalchemy, pydantic_settings, httpx, cryptography, multipart; print('Python runtime validation passed')"
    if ($LASTEXITCODE -ne 0) { throw "Bundled Python dependency validation failed with exit code $LASTEXITCODE" }
    & (Join-Path $toolsDir 'ffprobe.exe') -version | Select-Object -First 1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Bundled ffprobe validation failed with exit code $LASTEXITCODE" }
    $mediaInfo = Join-Path $toolsDir 'mediainfo.exe'
    if (Test-Path $mediaInfo) {
        & $mediaInfo --Version | Select-Object -First 2 | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Bundled MediaInfo validation failed with exit code $LASTEXITCODE" }
    }

    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\ReelIndex'
    New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    function New-Link([string]$Path,[string]$Target,[string]$Arguments,[string]$Description) {
        $shortcut = $shell.CreateShortcut($Path)
        $shortcut.TargetPath = $Target
        $shortcut.Arguments = $Arguments
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.Description = $Description
        $shortcut.Save()
    }
    New-Link (Join-Path $startMenu 'ReelIndex.lnk') $launcher '' 'Open ReelIndex movie inventory'
    New-Link (Join-Path $startMenu 'Stop ReelIndex.lnk') $launcher '--stop' 'Stop the local ReelIndex service'
    New-Link (Join-Path $startMenu 'View ReelIndex Logs.lnk') $launcher '--logs' 'Open ReelIndex log folder'
    New-Link (Join-Path $startMenu 'Uninstall ReelIndex.lnk') $uninstaller '' 'Remove ReelIndex'
    New-Link (Join-Path ([Environment]::GetFolderPath('Desktop')) 'ReelIndex.lnk') $launcher '' 'Open ReelIndex movie inventory'

    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ReelIndex'
    New-Item -Path $uninstallKey -Force | Out-Null
    Set-ItemProperty $uninstallKey DisplayName 'ReelIndex Movie Inventory'
    Set-ItemProperty $uninstallKey DisplayVersion $Version
    Set-ItemProperty $uninstallKey Publisher 'ReelIndex'
    Set-ItemProperty $uninstallKey InstallLocation $InstallDir
    Set-ItemProperty $uninstallKey DisplayIcon $launcher
    Set-ItemProperty $uninstallKey UninstallString ('"' + $uninstaller + '"')
    New-ItemProperty -Path $uninstallKey -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name EstimatedSize -Value ([int]((Get-ChildItem $InstallDir -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)) -PropertyType DWord -Force | Out-Null

    Write-Host "ReelIndex $Version offline installation completed successfully."
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
