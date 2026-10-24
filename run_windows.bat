@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python src\trainer.py
if errorlevel 1 goto fail
exit /b 0
:fail
pause
exit /b 1
