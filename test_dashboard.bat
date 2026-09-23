@echo off
cd /d "%~dp0"

echo ========================================================
echo Starting iPhone Dashboard Test Tool...
echo ========================================================
echo.

python test_dashboard.py %*

if %errorlevel% neq 0 (
    echo.
    echo [Error] Exited with code %errorlevel%.
)

echo.
pause
