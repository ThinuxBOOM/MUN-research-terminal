@echo off
setlocal
title MUN Research Station - fetch documents
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

echo This downloads UN documents into corpus\raw and then indexes them.
echo It needs an internet connection; the app itself does not.
echo.
python scripts\fetch_corpus.py core haiti
echo.
echo Anything listed as missing can be downloaded by hand into corpus\inbox,
echo then indexed from the Library page in the app.
pause
