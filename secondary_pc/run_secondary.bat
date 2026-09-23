@echo off
cd /d "%~dp0"

echo ========================================================
echo Starting Secondary PC Server (DeepSeek + iPhone Board)...
echo ========================================================

python main_secondary.py %*

if %errorlevel% neq 0 (
    echo.
    echo Program exited with error code %errorlevel%.
)

echo.
echo ========================================================
echo Process finished.
echo ========================================================
pause
