@echo off
setlocal
call "%~dp0_isolate.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\akrag.ps1" restart %*
