@echo off
setlocal
cd /d "%~dp0"
echo === WanderPin setup ===

REM pymobiledevice3 needs Python 3.12 (3.14 is too new for some of its parts on Windows)
call :has312
if errorlevel 1 (
  echo Python 3.12 not found - installing it now, please wait...
  py install 3.12
  call :has312
)
if errorlevel 1 (
  echo Trying winget instead...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  call :has312
)
if errorlevel 1 (
  echo.
  echo Could not install Python 3.12 automatically.
  echo Download "Python 3.12" from https://www.python.org/downloads/windows/ , install it, then run setup.bat again.
  pause & exit /b 1
)

REM Rebuild the environment if it was made with a different Python
if exist venv\Scripts\python.exe (
  venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)"
  if errorlevel 1 (
    echo Removing old environment made with the wrong Python...
    rmdir /s /q venv
  )
)
if not exist venv\Scripts\python.exe py -3.12 -m venv venv

venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
  echo.
  echo *** INSTALL FAILED - copy the first red ERROR lines above and send them to Claude ***
  pause & exit /b 1
)
venv\Scripts\python.exe -c "import uvicorn, fastapi, pymobiledevice3, webview; print('All packages OK')"
if errorlevel 1 (pause & exit /b 1)
echo.
echo Done! Now double-click start.bat
pause
exit /b 0

:has312
py -3.12 -c "import sys; print('PY312OK' if sys.version_info[:2]==(3,12) else 'NO')" 2>nul | findstr PY312OK >nul
exit /b %errorlevel%
