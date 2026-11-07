@echo off
setlocal
title MUN Research Station
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run install.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

echo Checking Ollama ...
ollama list >nul 2>nul
if errorlevel 1 (
  echo Ollama is not answering; starting it now ...
  start "" ollama serve
  timeout /t 4 /nobreak >nul
)

echo Starting MUN Research Station. The browser will open in a moment.
python scripts\run_server.py
pause
