#!/bin/bash
# 1688 → 蝦皮 上架小幫手（Mac 啟動）
cd "$(dirname "$0")"

# 優先用專案 venv（Homebrew Python 3.12 + Tk 9.0，深色模式正常顯示）。
# 系統 Python 3.9 的 Tk 8.5 在 macOS 深色模式會忽略 bg/fg 導致 GUI 隱形。
if [ -x ".venv/bin/python" ]; then
    echo "使用 .venv/bin/python ($(.venv/bin/python -c 'import tkinter; print(f"Tk {tkinter.TkVersion}")'))"
    exec .venv/bin/python gui.py
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
                exec "$PY" gui.py
            fi
        fi
    fi
done

echo "⚠️  找不到 Tk 8.6+ 的 Python，GUI 深色模式可能顯示異常"
python3 gui.py
