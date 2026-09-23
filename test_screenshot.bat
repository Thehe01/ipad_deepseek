@echo off
cd /d "%~dp0"

echo ========================================================
echo Starting Screenshot and Mouse Corner Test Tool...
echo ========================================================
echo.

python test_screenshot.py %*

if %errorlevel% neq 0 (
    echo.
    echo [Error] Exited with code %errorlevel%.
)

echo.
pause
