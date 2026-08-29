@echo off
setlocal
cd /d "%~dp0"
for %%I in ("%~dp0..\..\venv\Scripts\pythonw.exe") do set "UI_PY=%%~fI"
if not exist "%UI_PY%" for %%I in ("%~dp0..\..\venv\Scripts\python.exe") do set "UI_PY=%%~fI"
if not exist "%UI_PY%" set "UI_PY=pythonw"
start "" "%UI_PY%" "%~dp0python\clip_ui.py"
