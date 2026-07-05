@echo off
rem 1688 -> 蝦皮 上架小幫手（Windows 啟動）
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" gui.py
    goto :eof
)

python gui.py
if errorlevel 1 pause
