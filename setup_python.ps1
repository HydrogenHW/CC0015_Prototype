# Install a portable Python on a machine that has none.
#
# Why PowerShell: this script is invoked by run.bat precisely when Python is
# missing, so it cannot itself be a Python script. Windows ships PowerShell.
#
# The official .exe installer needs Windows Installer and admin rights; the
# NuGet package is a plain zip with a full CPython (pip + venv included) and
# needs neither. Result lands in %LOCALAPPDATA%\Programs\Python\Python313.

$ErrorActionPreference = "Stop"
$version = "3.13.16"
$target  = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313"
$zip     = Join-Path $env:TEMP "python-$version.zip"

if (Test-Path (Join-Path $target "python.exe")) {
    Write-Host "  Python already present at $target"
    exit 0
}

Write-Host "  Downloading Python $version (about 15 MB)..."
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {
    # older hosts may already default to TLS 1.2
}
Invoke-WebRequest -Uri "https://www.nuget.org/api/v2/package/python/$version" `
    -OutFile $zip -UseBasicParsing

Write-Host "  Extracting..."
$temp = "$target-tmp"
if (Test-Path $temp) { Remove-Item $temp -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $temp -Force

# The nupkg keeps the interpreter under tools\
New-Item -ItemType Directory -Path $target -Force | Out-Null
Move-Item (Join-Path $temp "tools\*") $target -Force

Remove-Item $temp -Recurse -Force
Remove-Item $zip -Force

$py = Join-Path $target "python.exe"
if (-not (Test-Path $py)) {
    Write-Host "  Extraction did not produce python.exe"
    exit 1
}

& $py --version
Write-Host "  Installed to $target"
exit 0
