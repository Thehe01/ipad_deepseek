@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo      [iPhone 手机常亮看板 · 本地扫码测试工具]
echo ========================================================
echo.

python test_dashboard.py

if %errorlevel% neq 0 (
    echo.
    echo [Error] 退出，错误码 %errorlevel%.
    pause
)
