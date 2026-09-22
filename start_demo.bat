@echo off
REM Demo mode: a pretend iPhone, for trying the app or taking store screenshots.
cd /d "%~dp0"
set WANDERPIN_DEMO=1
set WANDERPIN_PORT=8766
venv\Scripts\python.exe wanderpin.py
