param([Parameter(Mandatory=$true)][string]$InstallDir)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$runtimeDir = Join-Path $InstallDir 'runtime'
$toolsDir = Join-Path $InstallDir 'tools'
$appDir = Join-Path $InstallDir 'app'
$tempDir = Join-Path $env:TEMP ('ReelIndex-' + [Guid]::NewGuid().ToString('N'))
$logPath = Join-Path $env:TEMP 'ReelIndex-install.log'
try { Start-Transcript -Path $logPath -Force | Out-Null } catch {}
New-Item -ItemType Directory -Path $tempDir,$runtimeDir,$toolsDir -Force | Out-Null

function Get-RemoteFile([string]$Url,[string]$Destination,[string]$Label) {
    Write-Host "Downloading $Label..."
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

try {
    $pythonExe = Join-Path $runtimeDir 'python.exe'
    if (-not (Test-Path $pythonExe)) {
        $pythonZip = Join-Path $tempDir 'python.zip'
        Get-RemoteFile 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' $pythonZip 'Python runtime'
        Expand-Archive -Path $pythonZip -DestinationPath $runtimeDir -Force
    }

    $pthFile = Join-Path $runtimeDir 'python312._pth'
    @('python312.zip','.','Lib\site-packages','..\app','import site') | Set-Content -Path $pthFile -Encoding ASCII
    New-Item -ItemType Directory -Path (Join-Path $runtimeDir 'Lib\site-packages') -Force | Out-Null

    $getPip = Join-Path $tempDir 'get-pip.py'
    Get-RemoteFile 'https://bootstrap.pypa.io/get-pip.py' $getPip 'pip bootstrapper'
    Write-Host 'Installing Python packages...'
    & $pythonExe $getPip --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed with exit code $LASTEXITCODE" }
    & $pythonExe -m pip install --disable-pip-version-check --no-warn-script-location --upgrade -r (Join-Path $appDir 'requirements-windows.txt')
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed with exit code $LASTEXITCODE" }

    $ffprobeExe = Join-Path $toolsDir 'ffprobe.exe'
    if (-not (Test-Path $ffprobeExe)) {
        $ffmpegZip = Join-Path $tempDir 'ffmpeg.zip'
        $ffmpegExtract = Join-Path $tempDir 'ffmpeg'
        Get-RemoteFile 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $ffmpegZip 'FFmpeg/ffprobe'
        Expand-Archive -Path $ffmpegZip -DestinationPath $ffmpegExtract -Force
        $found = Get-ChildItem -Path $ffmpegExtract -Recurse -Filter 'ffprobe.exe' | Select-Object -First 1
        if (-not $found) { throw 'ffprobe.exe was not found in the downloaded FFmpeg package' }
        Copy-Item $found.FullName $ffprobeExe -Force
        $license = Get-ChildItem -Path $ffmpegExtract -Recurse -Filter 'LICENSE*' | Select-Object -First 1
        if ($license) { Copy-Item $license.FullName (Join-Path $toolsDir 'FFMPEG-LICENSE.txt') -Force }
    }

    $mediaInfoExe = Join-Path $toolsDir 'mediainfo.exe'
    if (-not (Test-Path $mediaInfoExe)) {
        $mediaInfoZip = Join-Path $tempDir 'mediainfo.zip'
        $mediaInfoExtract = Join-Path $tempDir 'mediainfo'
        Get-RemoteFile 'https://mediaarea.net/download/binary/mediainfo/26.05/MediaInfo_CLI_26.05_Windows_x64.zip' $mediaInfoZip 'MediaInfo CLI'
        Expand-Archive -Path $mediaInfoZip -DestinationPath $mediaInfoExtract -Force
        $foundMediaInfo = Get-ChildItem -Path $mediaInfoExtract -Recurse -Filter 'MediaInfo.exe' | Select-Object -First 1
        if (-not $foundMediaInfo) { throw 'MediaInfo.exe was not found in the downloaded MediaInfo package' }
        Copy-Item $foundMediaInfo.FullName $mediaInfoExe -Force
        Get-ChildItem -Path $foundMediaInfo.DirectoryName -Filter '*.dll' -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $toolsDir $_.Name) -Force }
        $mediaInfoLicense = Get-ChildItem -Path $mediaInfoExtract -Recurse -Filter 'LICENSE*' | Select-Object -First 1
        if ($mediaInfoLicense) { Copy-Item $mediaInfoLicense.FullName (Join-Path $toolsDir 'MEDIAINFO-LICENSE.txt') -Force }
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
    $launcher = Join-Path $InstallDir 'ReelIndex.exe'
    New-Link (Join-Path $startMenu 'ReelIndex.lnk') $launcher '' 'Open ReelIndex movie inventory'
    New-Link (Join-Path $startMenu 'Stop ReelIndex.lnk') $launcher '--stop' 'Stop the local ReelIndex service'
    New-Link (Join-Path $startMenu 'View ReelIndex Logs.lnk') $launcher '--logs' 'Open ReelIndex log folder'
    New-Link (Join-Path $startMenu 'Uninstall ReelIndex.lnk') (Join-Path $InstallDir 'Uninstall ReelIndex.exe') '' 'Remove ReelIndex'
    New-Link (Join-Path ([Environment]::GetFolderPath('Desktop')) 'ReelIndex.lnk') $launcher '' 'Open ReelIndex movie inventory'

    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ReelIndex'
    New-Item -Path $uninstallKey -Force | Out-Null
    Set-ItemProperty $uninstallKey DisplayName 'ReelIndex Movie Inventory'
    Set-ItemProperty $uninstallKey DisplayVersion '1.3.3'
    Set-ItemProperty $uninstallKey Publisher 'ReelIndex'
    Set-ItemProperty $uninstallKey InstallLocation $InstallDir
    Set-ItemProperty $uninstallKey DisplayIcon $launcher
    Set-ItemProperty $uninstallKey UninstallString ('"' + (Join-Path $InstallDir 'Uninstall ReelIndex.exe') + '"')
    New-ItemProperty -Path $uninstallKey -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null

    Write-Host 'ReelIndex installation completed.'
}
finally {
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    try { Stop-Transcript | Out-Null } catch {}
}
