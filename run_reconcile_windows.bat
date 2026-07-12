@echo off
rem 1688 訂單刷新（金流核對）（Windows 啟動）— 獨立金流核對 GUI（reconcile_gui.py）
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" reconcile_gui.py
    goto :eof
)

python reconcile_gui.py
if errorlevel 1 pause
