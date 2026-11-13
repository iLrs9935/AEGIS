@echo off
chcp 65001 > nul
cd /d "%~dp0.."
"aegis\python.exe" "tools\mark_all_cdkeys_used.py"
echo.
pause
