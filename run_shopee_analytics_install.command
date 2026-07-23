#!/bin/bash
# 安裝/重載 蝦皮數據中心每日抓取排程（LaunchAgent，每天 10:30 自動抓前一天）。
# 雙擊即可。之後完全不用碰終端機，資料每天早上自動長進 Google Sheet。
cd "$(dirname "$0")"

PLIST="com.joyslu.shopee-analytics.plist"
SRC="$(pwd)/config/$PLIST"
DEST="$HOME/Library/LaunchAgents/$PLIST"
LABEL="com.joyslu.shopee-analytics"

mkdir -p "$HOME/Library/LaunchAgents" logs

# 先卸載舊的（若有），再連結新的並載入
launchctl unload "$DEST" 2>/dev/null
ln -sf "$SRC" "$DEST"
launchctl load "$DEST"

echo "──────────────────────────────────────────"
echo "✅ 蝦皮每日抓取排程已安裝：$LABEL"
echo "   每天 10:30 自動抓前一天（商品/規格/大盤/廣告）→ Google Sheet"
echo "   來源 plist：$SRC"
echo "   日誌：$(pwd)/logs/shopee_analytics.log"
echo ""
echo "檢查是否已排程："
launchctl list | grep shopee-analytics && echo "→ 已排程 ✅" || echo "→ ⚠️ 沒看到，請看日誌"
echo "──────────────────────────────────────────"
echo "手動測跑一次：.venv/bin/python main.py shopee-collect-daily"
echo "停止排程：launchctl unload \"$DEST\""
echo "（按任意鍵關閉視窗）"
read -n 1 -s
