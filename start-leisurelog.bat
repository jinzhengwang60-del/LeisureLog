@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\leisurelog.ps1" -Action start -Port 8001
if errorlevel 1 pause
