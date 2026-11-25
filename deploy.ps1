<#
.SYNOPSIS
    RSBVP deploy for Windows PowerShell.

.DESCRIPTION
    Builds the web interface and starts the service: one command, one URL.

    This file must keep Windows (CRLF) line endings and plain ASCII text.

    Local research deployment only: no authentication, no TLS. Keep it on a
    trusted network. Nothing is downloaded except Python packages from PyPI and
    npm packages from the npm registry.

    Redeploying reuses everything: the .venv, the installed Python packages,
    node_modules and the built interface. Packages are only installed again when
    requirements.txt or package-lock.json changed, when a package is missing, or
    when the frontend sources are newer than the build.

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -Host 127.0.0.1 -Open
    .\deploy.ps1 -Stop
    .\deploy.ps1 -UnpackDataset
    .\deploy.ps1 -Status
    .\deploy.ps1 -Offline
    .\deploy.ps1 -Tls

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
    [switch]$Offline,
    [switch]$Status,
    [switch]$Recreate,
    [switch]$Rebuild,
    [switch]$Tls,
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

# --- find Python 3.10+ ------------------------------------------------------
$pythonCmd = $null
$pythonPre = @()
foreach ($candidate in @(@("py", @("-3")), @("python", @()), @("python3", @()))) {
    $exe = $candidate[0]
    $pre = $candidate[1]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        & $exe @pre -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonCmd = $exe; $pythonPre = $pre; break }
    }
}
if (-not $pythonCmd) {
    Say-Fail "Python 3.10+ was not found."
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

if ($Status) {
    & $pythonCmd @pythonPre deploy_env.py --check
    exit $LASTEXITCODE
}

# --- environment: venv + packages + node_modules + build --------------------
#  All of the caching logic lives in deploy_env.py, so Windows behaves exactly
#  like Linux/macOS. Nothing is reinstalled when nothing changed.
Say-Step "Preparing the environment"
$envArgs = @("deploy_env.py", "--build")
if ($SkipInstall) { $envArgs += "--skip-install" }
if ($Offline)     { $envArgs += "--offline" }
if ($Recreate)    { $envArgs += "--recreate" }
if ($Rebuild)     { $envArgs += "--rebuild" }
& $pythonCmd @pythonPre @envArgs
if ($LASTEXITCODE -ne 0) {
    Say-Fail "the deployment environment could not be prepared"
    Write-Host "            Diagnostics: .\deploy.ps1 -Status"
    exit 1
}
$venvPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (Test-Path $venvPython) { $pythonCmd = $venvPython; $pythonPre = @() }
if (-not (Test-Path "gui/frontend/dist/index.html")) {
    Say-Fail "gui/frontend/dist/index.html is missing after the build"
    exit 1
}

# --- start the service ------------------------------------------------------
Say-Step "Starting the service"
$deployArgs = @("deploy_server.py", "--dist", "gui/frontend/dist", "--host", $Host, "--port", $Port)
if ($Open)       { $deployArgs += "--open" }
if ($Foreground) { $deployArgs += "--foreground" }
if ($Tls)        { $deployArgs += "--tls" }

& $pythonCmd @pythonPre @deployArgs
if ($LASTEXITCODE -ne 0) {
    Say-Fail "deployment failed (exit $LASTEXITCODE) - see the messages above"
    exit $LASTEXITCODE
}
exit 0
