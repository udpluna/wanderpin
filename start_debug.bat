@echo off
REM Same as start.bat but keeps a console window open so you can see errors.
cd /d "%~dp0"
venv\Scripts\python.exe wanderpin.py %*
pause
