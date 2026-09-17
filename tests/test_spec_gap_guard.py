"""配號守門員回歸測試（免 pytest：`.venv/bin/python tests/test_spec_gap_guard.py`，不連網）。

擋的是這件事：配號靠「1688 規格原文」比對既有列，那一格空白就比不到 →
已經有品號的選項會被當成新的、**再發一個品號**（同一個選項兩個碼，獲利表對不起來，且不報錯）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.master_staging import (  # noqa: E402
    MasterContext, SpecGapBlocked, existing_spec_gaps, spec_gap_message,
)

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


def sku_row(code, name, spec1="", spec2=""):
    r = [""] * 16
    r[0], r[1], r[11], r[12] = code, name, spec1, spec2
    return r


CTX = MasterContext(
    product_rows=[["H-b7", "H.貼身衣褲", "b. 內衣", "蕾絲無鋼圈內衣"]],
    sku_rows=[
        sku_row("BH0020007000101", "H-b7_蕾絲無鋼圈內衣_黑,M", "黑色", "M"),
        sku_row("BH0020007000105", "H-b7_蕾絲無鋼圈內衣_黑,內褲"),          # 規格空白
        sku_row("BH0030002000101", "H-c2_蝴蝶結三角褲_白,M", "白色", "M"),
    ],
    shop="lady")


def prepared(code):
    return {"_meta": {"code": code}, "config": {"code": code}}


print("挑出空白")
g = existing_spec_gaps("lady", [prepared("H-b7")], CTX)
check("有空白的商品被挑出來", list(g) == ["H-b7"] and len(g["H-b7"]) == 1, g)
check("挑出的是那一列", g["H-b7"][0][0] == "BH0020007000105")
check("規格都有填的商品不擋", existing_spec_gaps("lady", [prepared("H-c2")], CTX) == {})
check("全新編號不擋（沒有既有列）", existing_spec_gaps("lady", [prepared("H-z99")], CTX) == {})
check("多支只回有問題的那支",
      list(existing_spec_gaps("lady", [prepared("H-c2"), prepared("H-b7")], CTX)) == ["H-b7"])

print("訊息")
m = spec_gap_message(g)
check("訊息含商品編號與品號", "H-b7" in m and "BH0020007000105" in m)
check("訊息講了為什麼與怎麼處理", "再發一個品號" in m and "標停售" in m)
check("例外帶得出 gaps", SpecGapBlocked(g).gaps == g)

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
