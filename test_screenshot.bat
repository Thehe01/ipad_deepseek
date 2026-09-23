@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo   [本地截屏与右上角鼠标停留 0.3s 截题 · 验证工具]
echo ========================================================
echo.

python test_screenshot.py

if %errorlevel% neq 0 (
    echo.
    echo [Error] 退出，错误码 %errorlevel%.
)

echo.
pause
