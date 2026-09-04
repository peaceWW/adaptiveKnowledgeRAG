@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\akrag.ps1" restart %*
