@echo off
REM One-tap launcher for the url2vid web UI on Windows.
REM
REM Mirrors start-web.sh: sets up whatever is missing, starts the server, and
REM opens a browser at it. Safe to run repeatedly. Pass a port as the first
REM argument to override 8000.

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM Re-invoked as a background helper further down; not for direct use.
if /i "%~1"=="--open-when-ready" goto openwhenready

set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"
set "PY=.venv\Scripts\python.exe"

echo(
echo   url2vid - starting up
echo(

where python >/dev/null 2>&1
if errorlevel 1 (
  echo   [X] Python is not installed, or not on PATH.
  echo       Get it from https://python.org/downloads - tick "Add Python to PATH".
  goto fail
)

where npm >/dev/null 2>&1
if errorlevel 1 (
  echo   [X] Node.js is not installed, or not on PATH.
  echo       Get it from https://nodejs.org
  goto fail
)

where ffmpeg >/dev/null 2>&1
if errorlevel 1 (
  echo   [!] ffmpeg is missing - video and audio cannot be merged into one file.
  echo       Install it with:  winget install Gyan.FFmpeg
)

REM Already running? Point the browser at it instead of failing on a port clash.
curl -fsS -m 2 "http://127.0.0.1:%PORT%/api/config" >/dev/null 2>&1
if not errorlevel 1 (
  echo   [OK] Already running on port %PORT% - opening it.
  start "" "http://127.0.0.1:%PORT%"
  exit /b 0
)

if not exist "%PY%" (
  echo   Creating the Python environment ^(first run only^)...
  python -m venv .venv || goto fail
)

REM Cheap presence check rather than a pip install on every launch.
"%PY%" -c "import fastapi, uvicorn, yt_dlp" >/dev/null 2>&1
if errorlevel 1 (
  echo   Installing Python packages ^(first run only^)...
  "%PY%" -m pip install --quiet --upgrade pip || goto fail
  "%PY%" -m pip install --quiet -r requirements.txt || goto fail
)

if not exist "web\node_modules" (
  echo   Installing frontend packages ^(first run only^)...
  pushd web
  call npm install --silent || (popd & goto fail)
  popd
)

if not exist "web\dist\index.html" (
  echo   Building the page...
  pushd web
  call npm run build --silent || (popd & goto fail)
  popd
)

echo   Starting the server on port %PORT%...
echo(

REM Opens the browser once the server answers, while the server itself runs in
REM the foreground so closing this window stops it.
start "" /b cmd /c ""%~f0" --open-when-ready %PORT%"

"%PY%" run_web.py --port %PORT%
exit /b %errorlevel%

:openwhenready
set "PORT=%~2"
for /l %%i in (1,1,60) do (
  curl -fsS -m 1 "http://127.0.0.1:%PORT%/api/config" >/dev/null 2>&1
  if not errorlevel 1 (
    start "" "http://127.0.0.1:%PORT%"
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)
exit /b 1

:fail
echo(
echo   Startup failed.
pause
exit /b 1
