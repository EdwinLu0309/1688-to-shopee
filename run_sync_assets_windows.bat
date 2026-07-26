@echo off
chcp 65001 >nul
rem 一鍵同步商品資產包（Windows 雙擊）
rem 先在主表「商品表」勾好「要產」欄，再雙擊我。跑完主表會標✓、資產包寫進雲端。
cd /d "%~dp0"

echo ================================================
echo  商品資產包 一鍵同步
echo  （讀主表勾選 -^> 抓取+產卡+寫雲端 -^> 回寫狀態）
echo ================================================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py sync-assets --shop nail
) else (
    python main.py sync-assets --shop nail
)

echo.
echo 跑完了。按任意鍵關閉。
pause >nul
