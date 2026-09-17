@echo off
REM Isolate this repo: use local .venv only; clear PYTHONPATH / PIP_TARGET.
for %%I in ("%~dp0..\..") do set "AKRAG_ROOT=%%~fI"
set "PYTHONPATH="
set "PYTHONHOME="
set "PIP_TARGET="
set "PIP_USER="
set "PYTHONSTARTUP="
set "PYTHONNOUSERSITE=1"
set "VIRTUAL_ENV=%AKRAG_ROOT%\.venv"
set "UV_PROJECT_ENVIRONMENT=%AKRAG_ROOT%\.venv"
if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PATH=%VIRTUAL_ENV%\Scripts;%PATH%"
