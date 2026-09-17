@echo off
setlocal
call "%~dp0scripts\windows\_isolate.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\akrag.ps1" start %*
