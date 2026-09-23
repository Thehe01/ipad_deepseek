@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo      [主机本地测试看板与写字板剪切板工具]
echo ========================================================
echo.

python test_dashboard.py

if %errorlevel% neq 0 (
    echo.
    echo [Error] 退出，错误码 %errorlevel%.
    pause
)
