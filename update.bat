@echo off
setlocal
title MUN Research Station - update
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo Run install.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
echo Updating Python packages. Your database and corpus are not touched.
python -m pip install --upgrade -r requirements.txt
python scripts\doctor.py
pause
