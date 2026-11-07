@echo off
setlocal
title MUN Research Station - backup
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python scripts\backup.py
pause
