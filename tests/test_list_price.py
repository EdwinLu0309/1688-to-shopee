"""AI 名單掛牌價回歸測試（免 pytest：`.venv/bin/python tests/test_list_price.py`，不連網）。

2026-09-19：Nail 名單「蝦皮設定售價」公式是空的 → 舊版退回抓「最後一個數字」＝最後定價（折後價）
→ LTL142 掛牌 69（應為 99），蝦皮再打 7 折＝賣便宜 30% 且不報錯。
"""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper.ai_list_reader import parse_ai_list_csv  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


d = Path(tempfile.mkdtemp())


def price(listed, final="69", discount="0.7", with_col=True):
    hdr = ["訂貨需求", "編號", "商品 or 品牌名稱", "分類", "標籤", "安全存量", "進貨網址", "選項說明", "商品成本", "最後定價"]
    row = ["現貨", "X1", "刷", "工具", "#N", "10", "https://detail.1688.com/offer/123.html", "", "1.95", final]
    if with_col:
        hdr.append("蝦皮設定售價")
        row.append(listed)
    rows = [["匯率", "4.975", "蝦皮折扣（最後定價÷這格＝掛牌價）", discount], hdr,
            ["預購 或 現貨", "※ 說明"] + [""] * (len(hdr) - 2), row]
    f = d / "a.csv"
    with open(f, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    ps = parse_ai_list_csv(f, shop="nail")
    return ps[0]["price"] if ps else None


check("有填掛牌價就照用", price("99") == 99)
check("掛牌價空白 → 最後定價÷折扣（不可拿 69 當掛牌價）", price("") == 99, price(""))
check("Lady 折扣 0.5", price("", final="345", discount="0.5") == 690)
check("掛牌價、最後定價都空 → 0（讓上游擋）", price("", final="") == 0)
check("說明列（※ 開頭）不當資料", price("99") is not None)
check("舊表沒有掛牌價欄 → 維持舊行為（最後一個數字）", price("", with_col=False) == 69)

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
