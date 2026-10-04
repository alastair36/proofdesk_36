@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python start.py %*
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py start.py %*
  ) else (
    echo Python is not installed. Get it from https://www.python.org/downloads/
    echo and tick "Add Python to PATH" during install, then run start again.
    pause
  )
)
