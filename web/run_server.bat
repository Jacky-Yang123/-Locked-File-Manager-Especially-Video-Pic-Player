@echo off
chcp 65001 >nul
title Locked Video Player - Web Backend
color 0A

echo =========================================
echo       Locked Video Player - Web Backend
echo =========================================
echo.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [Error] Cannot find virtual environment! Please ensure venv is created.
    pause
    exit /b
)

echo [Info] Starting backend service...
echo [Info] Close this window to stop the server, double click to restart.
echo.

venv\Scripts\python.exe app.py

echo.
echo [Info] Server stopped.
pause
