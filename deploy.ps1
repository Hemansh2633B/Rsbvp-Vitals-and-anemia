<#
.SYNOPSIS
    RSBVP deploy for Windows PowerShell.

.DESCRIPTION
    Builds the web interface and starts the service: one command, one URL.

    This file must keep Windows (CRLF) line endings and plain ASCII text.

    Local research deployment only: no authentication, no TLS. Keep it on a
    trusted network. Nothing is downloaded except Python packages from PyPI.

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -Host 127.0.0.1 -Open
    .\deploy.ps1 -Stop
    .\deploy.ps1 -UnpackDataset

.NOTES
    If PowerShell blocks the script ("running scripts is disabled"), either use
    deploy.cmd instead, or allow local scripts once:
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>
[CmdletBinding()]
param(
    [string]$Host = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$Open,
    [switch]$Stop,
    [switch]$Foreground,
    [switch]$SkipInstall,
    [switch]$UnpackDataset
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Say-Ok   { param([string]$Text) Write-Host "    [ok] $Text"   -ForegroundColor Green }
function Say-Fail { param([string]$Text) Write-Host "    [fail] $Text" -ForegroundColor Red }
function Say-Step { param([string]$Text) Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }

Write-Host "=============================================================="
Write-Host " RSBVP deploy  (Windows PowerShell)"
Write-Host "=============================================================="

# --- find Python 3.12+ ------------------------------------------------------
$pythonCmd = $null
$pythonPre = @()
foreach ($candidate in @(@("py", @("-3")), @("python", @()), @("python3", @()))) {
    $exe = $candidate[0]
    $pre = $candidate[1]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        & $exe @pre -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonCmd = $exe; $pythonPre = $pre; break }
    }
}
if (-not $pythonCmd) {
    Say-Fail "Python 3.12+ was not found."
    Write-Host "            Install it from https://www.python.org/downloads/ and tick"
    Write-Host "            'Add python.exe to PATH', then reopen PowerShell."
    exit 1
}
$version = & $pythonCmd @pythonPre -V 2>&1
Say-Ok "$version ($pythonCmd)"

if ($Stop) {
    & $pythonCmd @pythonPre deploy_server.py --stop
    exit $LASTEXITCODE
}

if ($UnpackDataset) {
    & $pythonCmd @pythonPre deploy_server.py --unpack-dataset
    exit $LASTEXITCODE
}

# --- python packages --------------------------------------------------------
if (-not $SkipInstall) {
    Say-Step "Installing Python packages"
    & $pythonCmd @pythonPre -m pip install -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Say-Fail "pip install failed - check your internet connection"
        exit 1
    }
    Say-Ok "Python packages ready"
}

# --- build the web interface ------------------------------------------------
Say-Step "Building the web interface"
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Say-Fail "npm (Node.js) not found - it is required to build the interface."
    Write-Host "            Install Node.js LTS from https://nodejs.org/ and re-run."
    exit 1
}
Push-Location "gui/frontend"
try {
    if (-not $SkipInstall) {
        npm ci --silent
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "the frontend build failed" }
} catch {
    Say-Fail $_.Exception.Message
    exit 1
} finally {
    Pop-Location
}
if (-not (Test-Path "gui/frontend/dist/index.html")) {
    Say-Fail "gui/frontend/dist/index.html is missing after the build"
    exit 1
}
Say-Ok "interface built: gui/frontend/dist"

# --- start the service ------------------------------------------------------
Say-Step "Starting the service"
$deployArgs = @("deploy_server.py", "--dist", "gui/frontend/dist", "--host", $Host, "--port", $Port)
if ($Open)       { $deployArgs += "--open" }
if ($Foreground) { $deployArgs += "--foreground" }

& $pythonCmd @pythonPre @deployArgs
if ($LASTEXITCODE -ne 0) {
    Say-Fail "deployment failed (exit $LASTEXITCODE) - see the messages above"
    exit $LASTEXITCODE
}
exit 0
