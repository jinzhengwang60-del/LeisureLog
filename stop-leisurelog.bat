@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\leisurelog.ps1" -Action stop -Port 8001
timeout /t 3 >nul
