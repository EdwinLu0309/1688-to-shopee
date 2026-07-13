#!/bin/bash
# 安裝/重載 1688 核對常駐監聽 daemon（LaunchAgent，開機自啟、背景常駐、免終端機）。
# 雙擊即可。之後你完全不用碰終端機，只在 Google Sheet 打勾。
cd "$(dirname "$0")"

PLIST="com.joyslu.reconcile-daemon.plist"
SRC="$(pwd)/config/$PLIST"
DEST="$HOME/Library/LaunchAgents/$PLIST"
LABEL="com.joyslu.reconcile-daemon"

mkdir -p "$HOME/Library/LaunchAgents" logs

# 先卸載舊的（若有），再連結新的並載入
launchctl unload "$DEST" 2>/dev/null
ln -sf "$SRC" "$DEST"
launchctl load "$DEST"

echo "──────────────────────────────────────────"
echo "✅ 常駐監聽已安裝並啟動：$LABEL"
echo "   來源 plist：$SRC"
echo "   日誌：$(pwd)/logs/reconcile_daemon.log"
echo ""
echo "檢查是否在跑："
launchctl list | grep reconcile-daemon && echo "→ 正在背景執行 ✅" || echo "→ ⚠️ 沒看到，請看日誌"
echo "──────────────────────────────────────────"
echo "停止：launchctl unload \"$DEST\""
echo "（按任意鍵關閉視窗）"
read -n 1 -s
