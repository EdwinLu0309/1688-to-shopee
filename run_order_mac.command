#!/bin/bash
# 每日訂貨小幫手（Mac 啟動）— 獨立訂貨 GUI（order_gui.py），與主上架 gui.py 分開
cd "$(dirname "$0")"

# 優先用專案 venv（Homebrew Python 3.12 + Tk 9.0，深色模式正常顯示）。
if [ -x ".venv/bin/python" ]; then
    echo "使用 .venv/bin/python ($(.venv/bin/python -c 'import tkinter; print(f"Tk {tkinter.TkVersion}")'))"
    exec .venv/bin/python order_gui.py
fi

for PY in \
    "/opt/homebrew/bin/python3.13" \
    "/opt/homebrew/bin/python3.12" \
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" \
    "/usr/local/bin/python3.12"; do
    if [ -x "$PY" ]; then
        TK_VER=$("$PY" -c "import tkinter; print(tkinter.TkVersion)" 2>/dev/null)
        if [ -n "$TK_VER" ]; then
            MAJOR=$(echo "$TK_VER" | cut -d. -f1)
            MINOR=$(echo "$TK_VER" | cut -d. -f2)
            if [ "$MAJOR" -gt 8 ] || { [ "$MAJOR" = "8" ] && [ "$MINOR" -ge 6 ]; }; then
                echo "使用 $PY (Tk $TK_VER)"
                exec "$PY" order_gui.py
            fi
        fi
    fi
done

echo "⚠️  找不到 Tk 8.6+ 的 Python，GUI 深色模式可能顯示異常"
python3 order_gui.py
