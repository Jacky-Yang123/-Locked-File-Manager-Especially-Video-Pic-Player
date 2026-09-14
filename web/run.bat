@echo off
title Locked Video Player - Web Edition
cd /d "%~dp0"

echo ═══════════════════════════════════════
echo   🔒 Locked Video Player - Web Edition
echo ═══════════════════════════════════════
echo.

REM Create venv if needed
if not exist "venv" (
    echo 📦 首次运行，创建虚拟环境...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dependencies
echo 📦 检查依赖...
pip install -q -r requirements.txt

echo.
echo 🚀 启动服务...
python app.py
pause
