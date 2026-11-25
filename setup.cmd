@echo off
REM ===========================================================================
REM  RSBVP setup for Windows — double-click this file, or run it in Command
REM  Prompt.  Everything below is described step by step in README.md under
REM  "Beginner setup (all platforms)".
REM
REM  What it does:  checks Python and Node.js, creates .venv, installs the
REM  Python and frontend dependencies, runs the tests, unpacks the bundled
REM  rPPG-10 dataset and validates it.
REM
REM  Nothing is downloaded from a dataset server, no webcam or GPU is needed.
REM  It never deletes your files.  Safe to run again at any time.
REM
REM  Options (any combination):
REM     setup.cmd --no-dataset      skip the dataset
REM     setup.cmd --dataset-only    only unpack + validate the dataset
REM     setup.cmd --no-frontend     skip the web interface
REM     setup.cmd --no-tests        install only, do not run tests
REM     setup.cmd --benchmark       also run the research benchmark (~3 min)
REM     setup.cmd --recreate        rebuild .venv from scratch
REM     setup.cmd --help
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ===========================================================================
echo  RSBVP setup (Windows)
echo ===========================================================================
echo.

REM ---- 1. Find Python ------------------------------------------------------
set "PY_EXE="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_EXE=py -3"
if not defined PY_EXE (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_EXE=python"
)
if not defined PY_EXE (
    echo [fail] Python 3.12 or newer was not found.
    echo.
    echo   1^) Download it from https://www.python.org/downloads/
    echo   2^) During installation TICK "Add python.exe to PATH"
    echo   3^) Close this window, open a new one, and run setup.cmd again
    echo.
    echo   Alternatively, install from the Microsoft Store: "Python 3.12"
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('%PY_EXE% -c "import sys; print('%%d.%%d.%%d' %% sys.version_info[:3])"') do set "PY_VERSION=%%v"
echo   [ok] Python !PY_VERSION!  ^(!PY_EXE!^)

REM ---- 2. Create the virtual environment ----------------------------------
if /i "%~1"=="--recreate" (
    if exist ".venv" (
        echo   [info] removing existing .venv ^(--recreate^)
        rmdir /s /q ".venv"
    )
)
if exist ".venv\Scripts\python.exe" (
    echo   [ok] .venv already exists ^(use --recreate to rebuild^)
) else (
    echo   [..] creating the virtual environment .venv
    %PY_EXE% -m venv .venv
    if errorlevel 1 (
        echo   [fail] could not create .venv
        pause
        exit /b 1
    )
    echo   [ok] created .venv
)
set "VPY=.venv\Scripts\python.exe"

REM ---- 3. Install dependencies --------------------------------------------
echo.
echo   [..] installing Python packages ^(a few minutes the first time^)
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install -r requirements-dev.txt
if errorlevel 1 (
    echo   [fail] dependency installation failed - check your internet connection
    pause
    exit /b 1
)
echo   [ok] Python dependencies installed

REM ---- 4. Python tests -----------------------------------------------------
set "SKIP_TESTS=0"
for %%a in (%*) do (
    if /i "%%a"=="--no-tests" set "SKIP_TESTS=1"
    if /i "%%a"=="--dataset-only" set "SKIP_TESTS=1"
)
if "!SKIP_TESTS!"=="0" (
    echo.
    echo   [..] running the Python test suite
    "%VPY%" -m pytest -q
    if errorlevel 1 (
        echo   [fail] some Python tests failed ^(see above^)
    ) else (
        echo   [ok] Python tests passed
    )
)

REM ---- 5. Frontend ---------------------------------------------------------
set "SKIP_FRONTEND=0"
for %%a in (%*) do (
    if /i "%%a"=="--no-frontend" set "SKIP_FRONTEND=1"
    if /i "%%a"=="--dataset-only" set "SKIP_FRONTEND=1"
    if /i "%%a"=="--no-dataset" set "NO_DATASET=1"
)
if "!SKIP_FRONTEND!"=="0" (
    where node >nul 2>&1
    if errorlevel 1 (
        echo   [warn] Node.js not found - skipping the web interface
        echo          Install the LTS version from https://nodejs.org/ if you want it
    ) else (
        echo.
        echo   [..] installing frontend packages in gui\frontend
        pushd gui\frontend
        call npm ci
        if errorlevel 1 (
            echo   [fail] npm ci failed
        ) else (
            echo   [ok] frontend packages installed
            if "!SKIP_TESTS!"=="0" (
                call npm test
                call npm run build
                call npm run lint
            )
        )
        popd
    )
)

REM ---- 6. Dataset ----------------------------------------------------------
if "!NO_DATASET!"=="1" (
    echo.
    echo   [info] dataset skipped ^(--no-dataset^)
) else (
    if exist "data\rPPG-10.zip" (
        echo.
        echo   [..] unpacking the bundled rPPG-10 dataset into data\rppg10
        set "DEST=data\rppg10"
        if not exist "!DEST!" mkdir "!DEST!"
        "%VPY%" -c "import sys, zipfile, pathlib; dest=pathlib.Path(sys.argv[2]); zipfile.ZipFile(sys.argv[1]).extractall(dest); inner=list(dest.rglob('Dataset_rPPG-10.zip')); [zipfile.ZipFile(str(p)).extractall(dest) for p in inner]; print('unpacked', len(inner), 'nested archive(s)')" "data\rPPG-10.zip" "!DEST!"
        if errorlevel 1 (
            echo   [fail] could not unpack data\rPPG-10.zip
        ) else (
            echo   [ok] dataset unpacked
            echo.
            echo   [..] validating the dataset ^(no signal values are read^)
            for /f "delims=" %%d in ('dir /b /s /ad "!DEST!\Dataset_rPPG-10" 2^>nul ^| findstr /e /i "Subject_1"') do set "SUBJ=%%d"
            if defined SUBJ (
                for %%p in ("!SUBJ!") do set "DROOT=%%~dp"
                set "DROOT=!DROOT:~0,-1!"
                "%VPY%" research\rppg10\run_benchmark.py inspect --data-root "!DROOT!" --output-dir reports\rppg10 --ecg-fs-hz 1000 --exclude-subjects 4
                echo   [ok] validation finished - see reports\rppg10\
            ) else (
                echo   [warn] could not locate Subject_1 in the unpacked dataset
            )
        )
    ) else (
        echo.
        echo   [warn] data\rPPG-10.zip not found - skipping the dataset
        echo          The rest of the project works without it.
    )
)

REM ---- 7. Optional benchmark ----------------------------------------------
for %%a in (%*) do (
    if /i "%%a"=="--benchmark" (
        echo.
        echo   [..] running the rPPG-10 benchmark ^(~3 minutes^)
        "%VPY%" research\rppg10\run_benchmark.py benchmark --data-root "!DROOT!" --output-dir reports\rppg10 --ecg-fs-hz 1000 --exclude-subjects 4 --allow-deviation --i-have-verified-the-licence
        echo   [ok] results written to reports\rppg10\rppg10_benchmark.md
    )
    if /i "%%a"=="--help" goto :usage
)
goto :done

:usage
echo.
echo Usage: setup.cmd [--no-dataset] [--dataset-only] [--no-frontend]
echo                   [--no-tests] [--benchmark] [--recreate] [--help]
echo.
echo   --no-dataset    skip unpacking/validating the bundled dataset
echo   --dataset-only  only unpack and validate the dataset
echo   --no-frontend   skip the web interface
echo   --no-tests      install dependencies but do not run tests
echo   --benchmark     also run the rPPG-10 research benchmark
echo   --recreate      delete and rebuild .venv
echo.

:done
echo.
echo ===========================================================================
echo  Done.
echo.
echo  Start the backend   ^(from the gui folder^):
echo     ..\.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
echo  Start the interface ^(in a second window^):
echo     cd gui\frontend ^&^& npm run dev -- --host 0.0.0.0
echo  Then open http://localhost:5173
echo.
echo  Research report: reports\rppg10\rppg10_benchmark.md
echo  This is research software, not a medical device.
echo ===========================================================================
echo.
pause
exit /b 0
