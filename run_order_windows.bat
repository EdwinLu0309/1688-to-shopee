@echo off
rem 每日訂貨小幫手（Windows 啟動）— 獨立訂貨 GUI（order_gui.py）
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" order_gui.py
    goto :eof
)

python order_gui.py
if errorlevel 1 pause
