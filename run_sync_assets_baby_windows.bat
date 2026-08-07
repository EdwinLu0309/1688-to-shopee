@echo off
chcp 65001 >nul
rem 【Baby】一鍵同步商品資產包（Windows 雙擊）
rem 先在 Baby 主表「蝦皮處理狀態」勾好「要產」欄，再雙擊我。跑完會標✓、資產包寫進雲端。
rem ★ 首次使用：把下面 set 那行的路徑改成你 Google Drive 掛的 Baby 商品資產夾（仿 Nail 的
rem   「G:\我的雲端硬碟\2. 賣場營運\1.【Nail】\【Nail】1. 商品\商品資產」找到 Baby 對應夾）。
cd /d "%~dp0"

set ASSET_CLOUD_BASE_BABY=G:\我的雲端硬碟\2. 賣場營運\【Baby】\【Baby】1. 商品\商品資產

echo ================================================
echo  【Baby】商品資產包 一鍵同步
echo  （讀主表勾選 -^> 抓取+產卡+寫雲端 -^> 回寫狀態）
echo ================================================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py sync-assets --shop baby
) else (
    python main.py sync-assets --shop baby
)

echo.
echo 跑完了。按任意鍵關閉。
pause >nul
