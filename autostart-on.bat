@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\leisurelog.ps1" -Action enable-autostart -Port 8001
pause
