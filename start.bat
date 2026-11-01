@echo off
chcp 65001 >nul
cd /d "%~dp0"
py app.py
if errorlevel 2 exit /b 0
if errorlevel 1 pause
