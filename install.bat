@echo off
setlocal
title MUN Research Station - install
cd /d "%~dp0"
echo ============================================================
echo   MUN Research Station - one-time setup
echo ============================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

echo [1/6] Checking Python ...
%PY% --version
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from https://python.org
  echo Tick "Add python.exe to PATH" during setup, then run install.bat again.
  pause
  exit /b 1
)

echo.
echo [2/6] Creating a virtual environment in .venv ...
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"

echo.
echo [3/6] Installing Python packages ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check your internet connection and try again.
  pause
  exit /b 1
)

echo.
echo [4/6] Checking Ollama ...
where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama was not found. Install it from https://ollama.com, then run install.bat again.
  pause
  exit /b 1
)
ollama list >nul 2>nul
if errorlevel 1 (
  echo Starting Ollama ...
  start "" ollama serve
  timeout /t 5 /nobreak >nul
)
echo Pulling qwen3:8b (about 5 GB the first time) ...
ollama pull qwen3:8b
echo Creating qwen3-mun with num_ctx 8192 ...
ollama create qwen3-mun -f Modelfile
echo Pulling the embedding model ...
ollama pull qwen3-embedding:0.6b

echo.
echo [5/6] Creating the database ...
python -c "from app.db import init_db; from app.ingest.pipeline import seed_reference_data; c=init_db(); seed_reference_data(c); print('Database ready.')"

echo.
echo [6/6] Running doctor ...
python scripts\doctor.py

echo.
echo Next steps:
echo   1. Double-click fetch.bat while online to download the UN documents.
echo   2. Double-click start.bat to open the app.
echo.
pause
