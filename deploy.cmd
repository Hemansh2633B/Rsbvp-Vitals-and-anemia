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
REM
REM  Redeploying is cheap: the .venv, the installed Python packages, node_modules
REM  and the built interface are all reused. Nothing is downloaded again unless
REM  requirements.txt or package-lock.json changed, a package is missing, or the
REM  frontend sources are newer than the build. Use --status to see what is cached
REM  and --offline to redeploy with no network at all.
REM
REM  Nothing is downloaded except Python packages from PyPI and npm packages from
REM  the npm registry. No webcam or GPU is needed to deploy. Local research
REM  deployment only: no authentication, no TLS - keep on a trusted network.
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
set "OFFLINE_ARG="
set "STATUS=0"
set "RECREATE_ARG="
set "REBUILD_ARG="

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--host" ( set "HOST=%~2" & shift & shift & goto parse )
if /i "%~1"=="--port" ( set "PORT=%~2" & shift & shift & goto parse )
if /i "%~1"=="--open" ( set "OPEN_ARG=--open" & shift & goto parse )
if /i "%~1"=="--foreground" ( set "FG_ARG=--foreground" & shift & goto parse )
if /i "%~1"=="--skip-install" ( set "SKIP_INSTALL=1" & shift & goto parse )
if /i "%~1"=="--offline" ( set "OFFLINE_ARG=--offline" & shift & goto parse )
if /i "%~1"=="--status" ( set "STATUS=1" & shift & goto parse )
if /i "%~1"=="--recreate" ( set "RECREATE_ARG=--recreate" & shift & goto parse )
if /i "%~1"=="--rebuild" ( set "REBUILD_ARG=--rebuild" & shift & goto parse )
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

REM ---- find Python 3.10+ -----------------------------------------------
set "PY="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo     [fail] Python 3.10+ was not found.
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

if "%STATUS%"=="1" (
    %PY% deploy_env.py --check
    exit /b %errorlevel%
)

REM ---- environment: venv + packages + node_modules + build ---------------
REM  All of the caching logic lives in deploy_env.py so Windows behaves exactly
REM  like Linux/macOS. Nothing is reinstalled when nothing changed.
echo.
echo ==^> Preparing the environment
set "ENV_ARGS=--build"
if "%SKIP_INSTALL%"=="1" set "ENV_ARGS=%ENV_ARGS% --skip-install"
if not "%OFFLINE_ARG%"=="" set "ENV_ARGS=%ENV_ARGS% --offline"
if not "%RECREATE_ARG%"=="" set "ENV_ARGS=%ENV_ARGS% --recreate"
if not "%REBUILD_ARG%"=="" set "ENV_ARGS=%ENV_ARGS% --rebuild"
%PY% deploy_env.py %ENV_ARGS%
if errorlevel 1 (
    echo     [fail] the deployment environment could not be prepared
    echo            Diagnostics: deploy.cmd --status
    echo.
    pause
    exit /b 1
)
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not exist "gui\frontend\dist\index.html" (
    echo     [fail] gui\frontend\dist\index.html is missing after the build
    echo.
    pause
    exit /b 1
)

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
echo Usage: deploy.cmd [--host ADDR] [--port N] [--open] [--stop] [--status]
echo                    [--foreground] [--skip-install] [--offline] [--recreate]
echo                    [--rebuild] [--unpack-dataset] [--help]
echo.
echo   --host ADDR      0.0.0.0 (default: this machine and local network)
echo   --port N         preferred port (default 8000; next free port if busy)
echo   --open           open the browser when ready
echo   --stop           stop a service started by this script
echo   --foreground     run attached to this window instead of background
echo   --skip-install   reuse what is installed (fail if packages are missing)
echo   --offline        redeploy with no network, from .cache\deploy
echo   --status         show what is installed/cached, change nothing, then exit
echo   --recreate       delete and rebuild .venv (repair; packages re-download)
echo   --rebuild        rebuild the interface even if it looks current
echo   --unpack-dataset only unpack the bundled rPPG-10 dataset, then exit
echo.
pause
exit /b 0
