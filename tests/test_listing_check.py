"""上架核對表組列回歸測試（免 pytest：`.venv/bin/python tests/test_listing_check.py`，不連網）。

守住：一個編號一列（多個 1688 來源合成一支）、選項/售價/品號同順序換行、規格圖缺幾張、
現貨/預購、重產時照編號更新原列（員工的勾不動）、新編號接在最後。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.listing_check import (  # noqa: E402
    CODE_COL, DATA_START, HEADERS, NP, URL_COL, build_check_rows, plan_rows,
)

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


def up(code, title, opt, price, sku, img=""):
    return {"ps_sku_parent_short": code, "ps_product_name": title,
            "et_title_option_for_variation_1": opt, "ps_price": price, "ps_sku_short": sku,
            "et_title_image_per_variation": img}


rows = build_check_rows(
    [up("HNV11", "吸塵器", "G1S", "2284", "AH01", "http://a"),
     up("HNV11", "吸塵器", "二合一", "3143", "AH02"),
     up("HNV11", "吸塵器", "濾網", "157", "AH03", "http://c"),
     up("HNL28", "美甲燈", "美規", "670", "AH09", "http://d")],
    [{"code": "HNV11", "item_id": "1", "demand": "現貨"},
     {"code": "HNV11", "item_id": "1", "demand": "現貨"},
     {"code": "HNV11", "item_id": "2", "demand": "現貨"},
     {"code": "HNL28", "item_id": "9", "demand": "預購"}],
    "2026-09-17", "文案_v1")

print("組列")
check("欄位數＝程式區", all(len(r) == NP for r in rows), [len(r) for r in rows])
check("一個編號一列", [r[CODE_COL] for r in rows] == ["HNV11", "HNL28"])
h = rows[0]
check("選項同順序換行", h[HEADERS.index("選項名稱")] == "G1S\n二合一\n濾網")
check("售價同順序", h[HEADERS.index("售價")] == "2284\n3143\n157")
check("品號同順序", h[HEADERS.index("SKU 品號")] == "AH01\nAH02\nAH03")
check("選項數", h[HEADERS.index("選項數")] == 3)
check("規格圖缺幾張", h[HEADERS.index("規格圖")] == "缺 1/3", h[HEADERS.index("規格圖")])
check("全有", rows[1][HEADERS.index("規格圖")] == "✅ 全有")
check("同網址不重複", h[URL_COL] == ["https://detail.1688.com/offer/1.html",
                                    "https://detail.1688.com/offer/2.html"], h[URL_COL])
check("現貨/預購", h[HEADERS.index("現貨/預購")] == "現貨" and rows[1][HEADERS.index("現貨/預購")] == "預購")

print("重產：照編號更新原列、新的接最後")
upd, add = plan_rows(["HNV1", "HNV11"], rows)
check("HNV11 更新第 2 支那一列", list(upd) == [DATA_START + 1], upd.keys())
check("HNL28 接在最後", [r[CODE_COL] for r in add] == ["HNL28"])
check("全新分頁全部新增", plan_rows([], rows)[1] == rows)

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
