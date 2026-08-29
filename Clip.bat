@echo off
setlocal
cd /d "%~dp0"
for %%I in ("%~dp0..\..\venv\Scripts\python.exe") do set "SESEFUS_CLIP_PYTHON=%%~fI"
if not exist "%SESEFUS_CLIP_PYTHON%" set "SESEFUS_CLIP_PYTHON="
if not defined SESEFUS_CLIP_PYTHON set "SESEFUS_CLIP_PYTHON=python"
set "SESEFUS_CLIP_HEAVY=%~dp0python\clip_heavy.py"
set "SESEFUS_CLIP_CONFIG_PY=%~dp0python\clip_config.py"
set "SESEFUS_CLIP_ALARM_PY=%~dp0python\clip_alarm.py"
if /i "%~1"=="alarm" goto :alarm
where zig >nul 2>&1
if errorlevel 1 (
  echo zig not on PATH. Controls:
  "%SESEFUS_CLIP_PYTHON%" "%SESEFUS_CLIP_CONFIG_PY%" %*
  goto :eof
)
zig build
if errorlevel 1 (
  echo zig build failed. Fix is in apps\journal-clip\src . Zig 0.16 only.
  exit /b 1
)
"zig-out\bin\journal-clip.exe" %*
goto :eof

:alarm
rem Time fires. Then you speak. No zig build, no port, no window.
rem shift does not rewrite %*, so the tail is rebuilt and re-quoted by hand.
shift
set "ALARM_ARGS="
:alarm_next
if "%~1"=="" goto :alarm_run
set "ALARM_ARGS=%ALARM_ARGS% "%~1""
shift
goto :alarm_next
:alarm_run
"%SESEFUS_CLIP_PYTHON%" "%SESEFUS_CLIP_ALARM_PY%"%ALARM_ARGS%
exit /b %errorlevel%
