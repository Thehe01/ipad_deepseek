@echo off
cd /d "%~dp0"

echo ========================================================
echo Starting Master PC Client (Tencent Meeting Monitor)...
echo ========================================================

python master_main.py %*

if %errorlevel% neq 0 (
    echo.
    echo Program exited with error code %errorlevel%.
)

echo.
echo ========================================================
echo Process finished.
echo ========================================================
pause
