"""
用尺碼數據做一張乾淨的繁體尺碼表圖片（PNG）。

蝦皮「圖片尺寸表」(Q 欄) 吃圖片網址（JPG/PNG，≤2MB，≤2048×2048）。
1688 附的尺碼表是簡體 + 含不相關欄位（如九分褲長），本模組把數據重繪成
繁體、只留需要的欄位，供 Edwin 上傳蝦皮後取得網址填回 Q 欄。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_BOLD = "/System/Library/Fonts/PingFang.ttc"


def make_size_chart(
    headers: list[str],
    rows: list[list[str]],
    output_path: Path,
    title: str = "尺碼表",
    unit: str = "單位：cm",
    note: str = "因人工測量方式不同，尺寸容許 1-3cm 誤差屬正常範圍。",
) -> Path:
    """畫一張表格圖。headers = 欄名；rows = 每列儲存格值（含尺碼欄）。"""
    W = 1080
    pad = 40
    n_cols = len(headers)
    col_w = (W - pad * 2) // n_cols
    row_h = 76
    header_h = 88
    title_h = 110
    n_rows = len(rows)
    H = title_h + header_h + row_h * n_rows + 120

    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(_FONT_BOLD, 54, index=1)
    f_head = ImageFont.truetype(_FONT_BOLD, 30, index=1)
    f_cell = ImageFont.truetype(_FONT_BOLD, 28, index=0)
    f_note = ImageFont.truetype(_FONT_BOLD, 22, index=0)

    def ctext(cx, cy, s, font, fill):
        b = d.textbbox((0, 0), s, font=font)
        d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2), s, font=font, fill=fill)

    # 標題
    ctext(W / 2, title_h / 2 + 6, title, f_title, "#2B2B2B")

    top = title_h
    accent = "#6B8E9E"
    # 表頭底色
    d.rectangle([pad, top, W - pad, top + header_h], fill=accent)
    for c, h in enumerate(headers):
        ctext(pad + col_w * c + col_w / 2, top + header_h / 2, h, f_head, "#FFFFFF")

    # 資料列
    y = top + header_h
    for r, row in enumerate(rows):
        bg = "#F4F7F8" if r % 2 == 0 else "#FFFFFF"
        d.rectangle([pad, y, W - pad, y + row_h], fill=bg)
        for c, val in enumerate(row):
            fill = "#2B2B2B" if c == 0 else "#444444"
            ctext(pad + col_w * c + col_w / 2, y + row_h / 2, str(val), f_cell, fill)
        y += row_h

    # 外框 + 直線
    d.rectangle([pad, top, W - pad, y], outline="#D5DEE2", width=2)
    for c in range(1, n_cols):
        d.line([pad + col_w * c, top, pad + col_w * c, y], fill="#D5DEE2", width=1)

    # 單位 + 提示
    ctext(W - pad - 90, y + 34, unit, f_note, "#888888")
    d.text((pad, y + 60), note, font=f_note, fill="#999999")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


if __name__ == "__main__":
    # P-a1 冰絲寬褲（長褲）— 依 1688 尺碼表 detail_020，去九分褲長、轉繁體
    headers = ["尺碼", "腰圍", "臀圍", "腳口", "前襠", "後襠", "褲長"]
    rows = [
        ["S", "63-73", "90", "56", "27", "37", "98"],
        ["M", "67-76", "94-97", "58", "27.5", "37.5", "98"],
        ["L", "70-80", "98-101", "60", "28", "38", "99"],
        ["XL", "74-84", "102-105", "62", "28.5", "38.5", "99"],
        ["2XL", "78-88", "106-109", "64", "29", "39", "100"],
        ["3XL", "84-92", "110-113", "66", "29.5", "39.5", "100"],
        ["4XL", "86-96", "114-117", "68", "30", "40", "101"],
    ]
    out = make_size_chart(headers, rows,
                          Path("output/784712770291/images/generated/size_chart_P-a1.png"),
                          title="冰絲寬褲 尺碼表")
    print("size chart:", out)
