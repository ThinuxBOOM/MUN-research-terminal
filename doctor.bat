@echo off
setlocal
title MUN Research Station - doctor
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python scripts\doctor.py
pause
