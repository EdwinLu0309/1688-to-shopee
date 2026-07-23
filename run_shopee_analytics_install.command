#!/bin/bash
# 安裝/重載 蝦皮數據中心每日抓取排程（LaunchAgent，每天 10:30 自動抓前一天）。
# 雙擊即可。之後完全不用碰終端機，資料每天早上自動長進 Google Sheet。
cd "$(dirname "$0")"

mkdir -p "$HOME/Library/LaunchAgents" logs

for PLIST in com.joyslu.shopee-analytics.plist com.joyslu.data-health.plist; do
    SRC="$(pwd)/config/$PLIST"
    DEST="$HOME/Library/LaunchAgents/$PLIST"
    launchctl unload "$DEST" 2>/dev/null
    ln -sf "$SRC" "$DEST"
    launchctl load "$DEST"
done

echo "──────────────────────────────────────────"
echo "✅ 蝦皮每日排程已安裝："
echo "   10:30 抓前一天（商品/規格/大盤/廣告）→ Google Sheet + 跑完跳通知"
echo "   11:00 健康點名（驗資料真的進來了沒）→ 跳「今日數據正常/異常」通知"
echo "   日誌：logs/shopee_analytics.log / logs/data_health.log"
echo ""
echo "檢查是否已排程："
launchctl list | grep -E "shopee-analytics|data-health" && echo "→ 已排程 ✅" || echo "→ ⚠️ 沒看到，請看日誌"
echo "──────────────────────────────────────────"
echo "手動測跑一次：.venv/bin/python main.py shopee-collect-daily"
echo "停止排程：launchctl unload \"$DEST\""
echo "（按任意鍵關閉視窗）"
read -n 1 -s
