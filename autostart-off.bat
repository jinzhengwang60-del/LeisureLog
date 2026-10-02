@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\leisurelog.ps1" -Action disable-autostart -Port 8001
pause
