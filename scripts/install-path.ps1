# Install zhuque / zhuque-mur / zhu-mur / zhu onto the user PATH.
# Shims live in ~/.local/bin and call this checkout's Poetry venv.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$bin = Join-Path $env:USERPROFILE ".local\bin"
$names = @("zhuque", "zhuque-mur", "zhu-mur", "zhu")

if (-not (Test-Path $python)) {
    Write-Host "Poetry venv missing. Run: poetry install"
    exit 1
}

New-Item -ItemType Directory -Force -Path $bin | Out-Null

$shim = @"
@echo off
"$python" -m zhuque_mur %*
"@

foreach ($name in $names) {
    $path = Join-Path $bin "$name.cmd"
    Set-Content -Path $path -Value $shim -Encoding ascii
    Write-Host "Installed $path"
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$bin*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$bin", "User")
    Write-Host "Added $bin to the user PATH. Open a new terminal."
} else {
    Write-Host "$bin is already on the user PATH."
}

Write-Host "Try: zhuque"
