<#
.SYNOPSIS
    RSBVP one-command setup for Windows PowerShell.

.DESCRIPTION
    Checks Python 3.12+ and Node.js, creates .venv, installs the Python and
    frontend dependencies, runs the tests, unpacks the bundled rPPG-10 dataset
    and validates it.  Never downloads a dataset, never needs a webcam or GPU.

    If PowerShell refuses to run this file ("running scripts is disabled"),
    you can either use setup.cmd instead (simplest for beginners), or allow
    scripts for your user account once:
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

    Beginner walkthrough: README.md -> "Beginner setup (all platforms)".

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -NoDataset
    .\setup.ps1 -Benchmark
#>
[CmdletBinding()]
param(
    [switch]$NoDataset,
    [switch]$DatasetOnly,
    [switch]$NoFrontend,
    [switch]$NoTests,
    [switch]$Benchmark,
    [switch]$Recreate,
    [string]$Dest = "data/rppg10",
    [int]$EcgFsHz = 1000,
    [int[]]$ExcludeSubjects = @(4)
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Write-Step { param([string]$Text) Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "  [ok] $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "  [warn] $Text" -ForegroundColor Yellow }
function Write-Err  { param([string]$Text) Write-Host "  [fail] $Text" -ForegroundColor Red }
function Write-Info { param([string]$Text) Write-Host "        $Text" }

Write-Host "RSBVP setup (Windows PowerShell)" -ForegroundColor White
Write-Host "repository: $PSScriptRoot"

$script:Failures = 0

# --- Python -----------------------------------------------------------------
Write-Step "Checking Python"
$pythonExe = $null
$pythonArgs = @()
foreach ($candidate in @(@("py", @("-3")), @("python", @()), @("python3", @()))) {
    $exe = $candidate[0]
    $pre = $candidate[1]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        try {
            & $exe @pre -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $pythonExe = $exe; $pythonArgs = $pre; break }
        } catch { }
    }
}
if (-not $pythonExe) {
    Write-Err "Python 3.12 or newer was not found."
    Write-Info "Install it from https://www.python.org/downloads/ and TICK 'Add python.exe to PATH'."
    Write-Info "Alternative: install 'Python 3.12' from the Microsoft Store, then reopen PowerShell."
    exit 1
}
$pyVersion = & $pythonExe @pythonArgs -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
Write-Ok "Python $pyVersion ($pythonExe)"
if ($DatasetOnly) { Write-Info "dataset-only mode: skipping environment and frontend" }

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not $DatasetOnly) {
    # --- virtual environment -------------------------------------------------
    Write-Step "Creating the Python virtual environment (.venv)"
    if ($Recreate -and (Test-Path ".venv")) {
        Write-Info "removing existing .venv (-Recreate)"
        Remove-Item -Recurse -Force ".venv"
    }
    if (Test-Path $venvPy) {
        Write-Ok ".venv already exists (use -Recreate to rebuild)"
    } else {
        & $pythonExe @pythonArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { Write-Err "could not create .venv"; exit 1 }
        Write-Ok "created .venv"
    }

    # --- dependencies --------------------------------------------------------
    Write-Step "Installing Python dependencies (a few minutes)"
    & $venvPy -m pip install --upgrade pip | Out-Null
    & $venvPy -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Err "dependency installation failed - check your internet connection"
        exit 1
    }
    Write-Ok "Python dependencies installed"

    # --- tests ---------------------------------------------------------------
    if (-not $NoTests) {
        Write-Step "Running the Python test suite (dataset-free)"
        & $venvPy -m pytest -q
        if ($LASTEXITCODE -ne 0) { $script:Failures++; Write-Err "some Python tests failed" }
        else { Write-Ok "Python tests passed" }
    }

    # --- frontend ------------------------------------------------------------
    if (-not $NoFrontend) {
        Write-Step "Installing and testing the web interface (gui/frontend)"
        if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
            $script:Failures++
            Write-Err "Node.js was not found (only needed for the web interface)."
            Write-Info "Install the LTS version from https://nodejs.org/, or re-run with -NoFrontend."
        } else {
            Push-Location "gui/frontend"
            try {
                npm ci
                if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
                if (-not $NoTests) {
                    npm test
                    if ($LASTEXITCODE -ne 0) { throw "npm test failed" }
                    npm run build
                    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
                    npm run lint
                    if ($LASTEXITCODE -ne 0) { throw "npm run lint failed" }
                }
                Write-Ok "frontend ready"
            } catch {
                $script:Failures++
                Write-Err $_.Exception.Message
            } finally {
                Pop-Location
            }
        }
    }
}

# --- dataset ----------------------------------------------------------------
$datasetRoot = $null
if ($NoDataset) {
    Write-Info "dataset skipped (-NoDataset)"
} else {
    Write-Step "Unpacking the bundled rPPG-10 dataset"
    $zip = "data/rPPG-10.zip"
    if (-not (Test-Path $zip)) {
        Write-Warn "$zip not present - skipping the dataset (the rest works without it)"
        Write-Info "See docs/RPPG10_VALIDATION.md for how to obtain it (CC BY-NC-SA 4.0)."
    } else {
        New-Item -ItemType Directory -Force -Path $Dest | Out-Null
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path $zip), (Resolve-Path $Dest), $true)
        # the provider ships a zip inside a zip
        Get-ChildItem -Path $Dest -Recurse -Filter "Dataset_rPPG-10.zip" | ForEach-Object {
            Write-Info "found nested archive: $($_.Name)"
            [System.IO.Compression.ZipFile]::ExtractToDirectory($_.FullName, (Resolve-Path $Dest), $true)
        }
        $subject1 = Get-ChildItem -Path $Dest -Recurse -Directory -Filter "Subject_1" |
                    Select-Object -First 1
        if (-not $subject1) {
            $script:Failures++
            Write-Err "could not locate Subject_1 inside $Dest"
        } else {
            $datasetRoot = $subject1.Parent.FullName
            Write-Ok "dataset unpacked at $datasetRoot"

            if ($DatasetOnly -and -not (Test-Path $venvPy)) {
                Write-Warn "no virtual environment yet; skipping validation (run without -DatasetOnly first)"
            } else {
                Write-Step "Validating the dataset (no signal values are read)"
                & $venvPy research/rppg10/run_benchmark.py inspect `
                    --data-root $datasetRoot --output-dir reports/rppg10 `
                    --ecg-fs-hz $EcgFsHz --exclude-subjects $ExcludeSubjects
                switch ($LASTEXITCODE) {
                    0 { Write-Ok "dataset validated with no problems" }
                    2 { Write-Warn "validation reported items to review (normal: the provider spreadsheet is a known deviation)"; }
                    default { $script:Failures++; Write-Err "dataset validation crashed" }
                }
            }
        }
    }
}

# --- optional benchmark -----------------------------------------------------
if ($Benchmark) {
    Write-Step "Running the rPPG-10 research benchmark (~3 minutes)"
    if (-not $datasetRoot) { $script:Failures++; Write-Err "-Benchmark needs the dataset" }
    else {
        & $venvPy research/rppg10/run_benchmark.py benchmark `
            --data-root $datasetRoot --output-dir reports/rppg10 `
            --ecg-fs-hz $EcgFsHz --exclude-subjects $ExcludeSubjects `
            --allow-deviation --i-have-verified-the-licence
        if ($LASTEXITCODE -ne 0) { $script:Failures++; Write-Err "benchmark failed" }
        else { Write-Ok "results written to reports/rppg10/rppg10_benchmark.md" }
    }
}

# --- summary ----------------------------------------------------------------
Write-Step "Summary"
if ($script:Failures -eq 0) { Write-Host "All steps completed." -ForegroundColor Green }
else { Write-Host "$($script:Failures) step(s) need attention (see [fail] lines above)." -ForegroundColor Red }

@"

What to do next
  1. Start the backend (from the gui folder):
       ..\.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
  2. Start the web interface (second PowerShell window):
       cd gui\frontend ; npm run dev -- --host 0.0.0.0
  3. Open http://localhost:5173 in your browser (camera permission is required).

Reports: reports\rppg10\rppg10_benchmark.md
Docs:    README.md | docs\RPPG10_VALIDATION.md

Research software only - not a medical device. The bundled rPPG-10 dataset is
CC BY-NC-SA 4.0 (non-commercial, share-alike) and is the one deliberate exception
to this repository's "no datasets in Git" rule.
"@ | Write-Host

exit $script:Failures
