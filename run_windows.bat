@echo off
chcp 65001 >nul
rem 1688 -> 蝦皮 上架小幫手（Windows 啟動）
rem ⚠️ PYTHONUTF8=1 不可拿掉：Windows 主控台預設 cp950，印 ✅ ✓ 這類符號會 UnicodeEncodeError
rem    把子程序整個弄當（#S242 實際踩過：cookie-hub 登入其實成功、視窗卻報「登入未完成」）。
rem    settings.py 的 reconfigure 只救得到本程序，救不到 subprocess 開出去的子程序。
set PYTHONUTF8=1
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" gui.py
    goto :eof
)

python gui.py
if errorlevel 1 pause
