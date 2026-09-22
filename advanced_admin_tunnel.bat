@echo off
REM FALLBACK ONLY - if "Connect" keeps failing at "Opening secure tunnel".
REM 1) Right-click this file > Run as administrator and leave the window open.
REM 2) Then start the app with start_debug.bat after running:  set WANDERPIN_TRANSPORT=tunneld
cd /d "%~dp0"
venv\Scripts\python.exe -m pymobiledevice3 remote tunneld
pause
