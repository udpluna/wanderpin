@echo off
setlocal
cd /d "%~dp0\.."
echo === Building the Windows app ===
if not exist venv\Scripts\python.exe (echo Run setup.bat first. & pause & exit /b 1)
venv\Scripts\python.exe -m pip install --upgrade pyinstaller
if errorlevel 1 (echo Could not install PyInstaller & pause & exit /b 1)
venv\Scripts\python.exe -m PyInstaller build\wanderpin.spec --noconfirm --distpath dist --workpath build\work
if errorlevel 1 (echo. & echo *** BUILD FAILED - send the red errors above to Claude *** & pause & exit /b 1)
echo.
echo App built:  dist\WanderPin\WanderPin.exe
echo.
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% build\installer.iss
  echo Installer built in dist\installer
) else (
  echo To also make a Setup.exe installer, install Inno Setup 6 ^(free, jrsoftware.org^) and run this again.
)
pause
