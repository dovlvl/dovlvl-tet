@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python -m unittest discover -s tests -v
if errorlevel 1 goto fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name TetrisTrainer_v06_fixed --paths src --manifest packaging\app.manifest src\trainer.py
if errorlevel 1 goto fail
start "" dist
pause
exit /b 0
:fail
echo BUILD FAILED. See errors above. Python 3.11+ x64 with Tcl/Tk is required.
pause
exit /b 1
