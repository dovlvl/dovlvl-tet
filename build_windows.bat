@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements-lock.txt
if errorlevel 1 goto fail
.venv\Scripts\python -m unittest discover -s tests -v
if errorlevel 1 goto fail
.venv\Scripts\python tools\build_exe.py --name TetrisAuto --verify-startup
if errorlevel 1 goto fail
start "" dist
pause
exit /b 0
:fail
echo BUILD FAILED. See errors above. Python 3.11+ x64 with Tcl/Tk is required.
pause
exit /b 1
