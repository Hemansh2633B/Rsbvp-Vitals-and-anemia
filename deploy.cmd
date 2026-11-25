@echo off
REM ===========================================================================
REM  RSBVP deploy - Windows (Command Prompt)
REM ===========================================================================
REM  Builds the web interface and starts the service. One command, one URL.
REM
REM     deploy.cmd                 deploy on http://localhost:8000 (LAN-reachable)
REM     deploy.cmd --host 127.0.0.1 this machine only (no LAN access)
REM     deploy.cmd --open          open the browser when ready
REM     deploy.cmd --stop          stop the running service
REM     deploy.cmd --foreground    run attached to this window (default: background)
REM     deploy.cmd --help
REM
REM  This file must keep Windows (CRLF) line endings and plain ASCII text.
REM  Nothing is downloaded except Python packages from PyPI. No webcam or GPU is
REM  needed to deploy. Local research deployment only: no authentication, no TLS -
REM  keep it on a trusted network.
REM ===========================================================================

setlocal
cd /d "%~dp0"

set "HOST=0.0.0.0"
set "PORT=8000"
set "OPEN_ARG="
set "FG_ARG="
set "SKIP_INSTALL=0"
set "STOP=0"
set "UNPACK=0"

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--host" ( set "HOST=%~2" & shift & shift & goto parse )
if /i "%~1"=="--port" ( set "PORT=%~2" & shift & shift & goto parse )
if /i "%~1"=="--open" ( set "OPEN_ARG=--open" & shift & goto parse )
if /i "%~1"=="--foreground" ( set "FG_ARG=--foreground" & shift & goto parse )
if /i "%~1"=="--skip-install" ( set "SKIP_INSTALL=1" & shift & goto parse )
if /i "%~1"=="--stop" ( set "STOP=1" & shift & goto parse )
if /i "%~1"=="--unpack-dataset" ( set "UNPACK=1" & shift & goto parse )
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage
echo Unknown option: %~1
goto usage

:parsed
echo ==============================================================
echo  RSBVP deploy  (Windows)
echo ==============================================================

REM ---- find Python 3.12+ -----------------------------------------------
set "PY="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo     [fail] Python 3.12+ was not found.
    echo            Install it from https://www.python.org/downloads/
    echo            and TICK "Add python.exe to PATH", then reopen this window.
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('%PY% -V 2^>^&1') do set "PYVER=%%v"
echo     [ok] %PYVER%  ^(%PY%^)

REM ---- stop mode --------------------------------------------------------
if "%STOP%"=="1" (
    %PY% deploy_server.py --stop
    exit /b %errorlevel%
)

if "%UNPACK%"=="1" (
    %PY% deploy_server.py --unpack-dataset
    exit /b %errorlevel%
)

REM ---- Python packages --------------------------------------------------
if "%SKIP_INSTALL%"=="0" (
    echo.
    echo ==^> Installing Python packages
    %PY% -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo     [fail] pip install failed - check your internet connection
        echo.
        pause
        exit /b 1
    )
    echo     [ok] Python packages ready
)

REM ---- build the web interface -----------------------------------------
echo.
echo ==^> Building the web interface
where npm >nul 2>&1
if errorlevel 1 (
    echo     [fail] npm ^(Node.js^) not found - it is required to build the interface.
    echo            Install Node.js LTS from https://nodejs.org/ and re-run.
    echo.
    pause
    exit /b 1
)
pushd gui\frontend
if "%SKIP_INSTALL%"=="0" (
    call npm ci --silent
    if errorlevel 1 (
        popd
        echo     [fail] npm ci failed
        echo.
        pause
        exit /b 1
    )
)
call npm run build
if errorlevel 1 (
    popd
    echo     [fail] the frontend build failed
    echo.
    pause
    exit /b 1
)
popd
if not exist "gui\frontend\dist\index.html" (
    echo     [fail] gui\frontend\dist\index.html is missing after the build
    echo.
    pause
    exit /b 1
)
echo     [ok] interface built: gui\frontend\dist

REM ---- start the service -----------------------------------------------
echo.
echo ==^> Starting the service
%PY% deploy_server.py --dist gui\frontend\dist --host %HOST% --port %PORT% %OPEN_ARG% %FG_ARG%
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo     [fail] deployment failed ^(exit %RC%^) - see the messages above
    echo.
    pause
    exit /b %RC%
)
echo.
pause
exit /b 0

:usage
echo.
echo Usage: deploy.cmd [--host ADDR] [--port N] [--open] [--stop] [--unpack-dataset]
echo                    [--foreground] [--skip-install] [--help]
echo.
echo   --host ADDR      0.0.0.0 (default: this machine and local network)
echo   --port N         preferred port (default 8000; next free port if busy)
echo   --open           open the browser when ready
echo   --stop           stop a service started by this script
echo   --foreground     run attached to this window instead of background
echo   --skip-install   skip pip install and npm ci
echo   --unpack-dataset only unpack the bundled rPPG-10 dataset, then exit
echo.
pause
exit /b 0
