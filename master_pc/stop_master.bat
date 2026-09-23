@echo off
cd /d "%~dp0"

echo ========================================================
echo Stopping Master PC Background Process...
echo ========================================================
echo.

python stop_master.py

echo.
pause
