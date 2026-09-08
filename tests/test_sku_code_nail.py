"""Nail SKU 品號生成器回歸測試（免 pytest：`.venv/bin/python tests/test_sku_code_nail.py`）。

樣本取自 2026-09-07 線上 Nail 1-1 實際資料。守住的重點：
①結構對（用真實品號對答案）②發號一律 max+1 不補空號 ③append-only 不重編
④未知品牌一定拋錯不自己編 ⑤**商品序由「商品編號存不存在」決定**——新編號開新序、
既有編號接款式（2026-09-08 Edwin 釐清，原本的「歸屬」欄因此移除）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.sku_code import ExistingRow  # noqa: E402
from scraper.sku_code_nail import (  # noqa: E402
    BadNailCode, NailContext, UnknownBrand, allocate, build_code, parse_product_code,
)

FAILED = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {extra}")
        FAILED.append(name)


def eq(name, got, want):
    check(name, got == want, f"\n     got ={got!r}\n     want={want!r}")


# ── 線上真實樣本（品號, 品名）──
REAL = [
    ("AA0060001010000", "AAS1_黑瓶平衡液"),
    ("AA0060001020000", "AAS1_黑瓶無酸底漆"),
    ("AA0060001030000", "AAS1_黑瓶可卸底膠"),
    ("AA0060001040000", "AAS1_黑瓶加固膠"),
    ("AA0060002010000", "AAS2_紅瓶功能膠"),
    ("AA0060003010000", "AAS4_罐裝多功能透明膠"),
    ("AA0060003020000", "AAS6_罐裝硬式免洗封層"),
    ("AA0120001010000", "AVD1_綠瓶經典功能膠"),
    ("AA0120002010000", "AVD2_升級彩色瓶特殊膠"),
    ("AA0010008010000", "AIL1_兔子膠_免洗封層"),
]
ROWS = [[c, n] + [""] * 11 for c, n in REAL]
CTX = NailContext.from_sku_rows(ROWS)


def test_parse():
    print("\n[1] Nail 商品編號解析（無連字號，與 Lady 不同）")
    pc = parse_product_code("AAS1")
    eq("AAS1 → 分類/品牌/序號", (pc.cat, pc.brand, pc.seq), ("A", "AS", 1))
    eq("AVD13 → 品牌 VD", parse_product_code("AVD13").brand, "VD")
    eq("AIL1 → 品牌 IL", parse_product_code("AIL1").brand, "IL")
    for bad in ("H-c2", "CHE", "", "123"):
        try:
            parse_product_code(bad)
            check(f"{bad!r} 要拋錯", False, "竟然解析成功")
        except BadNailCode:
            check(f"{bad!r} 要拋錯", True)


def test_context_from_real_data():
    print("\n[2] 從既有資料推導品牌碼與最大號（不寫死）")
    eq("AS → 006", CTX.brand_code("A", "AS"), "006")
    eq("VD → 012", CTX.brand_code("A", "VD"), "012")
    eq("IL → 001", CTX.brand_code("A", "IL"), "001")
    eq("AS 現有最大商品序 = 3", CTX.max_item_seq[("A", "006")], 3)
    eq("AS 商品序 0001 的既有款式", CTX.styles_of[("A", "006", 1)], {1, 2, 3, 4})
    eq("AAS1 對到商品序 1", CTX.item_seq_of_code["AAS1"], 1)


def test_build_matches_real_codes():
    print("\n[3] 組碼對真實品號")
    eq("AAS1 款式01", build_code("A", "006", 1, 1, 0), "AA0060001010000")
    eq("AAS1 款式04", build_code("A", "006", 1, 4, 0), "AA0060001040000")
    eq("AVD2", build_code("A", "012", 2, 1, 0), "AA0120002010000")
    eq("長度固定 15", len(build_code("A", "006", 9999, 99, 9999)), 15)


def test_unknown_brand_raises():
    print("\n[4] 未知品牌一定拋錯，不自己編號（會撞號且不報錯）")
    try:
        CTX.brand_code("A", "ZZ")
        check("未知品牌要拋 UnknownBrand", False, "竟然給了號")
    except UnknownBrand as e:
        check("未知品牌要拋 UnknownBrand", True)
        check("訊息要提示『最大+1會是幾號』", "013" in str(e), str(e)[:90])


def test_new_product_gets_max_plus_one():
    print("\n[5] 新品：商品序 = 該品牌最大 + 1（不補中間空號）")
    res = allocate("AAS20", [("色號01", ""), ("色號02", ""), ("色號03", "")], [], CTX)
    eq("商品序 = 3+1 = 4", res.item_seq, 4)
    eq("款式從 01 起", res.style_seq, 1)
    check("是新開商品序", res.new_item)
    eq("三個規格 → 顏色 0001~0003",
       [a.sku_code for a in res.allocations],
       ["AA0060004010001", "AA0060004010002", "AA0060004010003"])
    check("不與既有品號相同",
          not ({a.sku_code for a in res.allocations} & {c for c, _ in REAL}))


def test_no_spec_product_gets_color_0000():
    print("\n[6] 完全沒有規格的商品 → 顏色序 0000")
    res = allocate("AAS20", [("", "")], [], CTX)
    eq("顏色 0000", res.allocations[0].sku_code, "AA0060004010000")


def test_existing_code_continues_style():
    print("\n[7] 既有編號 → 沿用它的商品序，款式接在現有最大之後")
    res = allocate("AAS1", [("皮草封層", "")], [], CTX)
    eq("商品序沿用 AAS1 的 0001", res.item_seq, 1)
    eq("款式 = 既有最大4 + 1 = 5", res.style_seq, 5)
    check("不是新開商品序", not res.new_item)
    eq("品號", res.allocations[0].sku_code, "AA0060001050001")
    check("不與既有品號相同",
          res.allocations[0].sku_code not in {c for c, _ in REAL})


def test_new_code_never_lands_on_existing_item():
    print("\n[8] ⚠️ 新編號一定開新商品序，不可掉進既有編號的號段")
    res = allocate("AAS99", [("x", "")], [], CTX)
    check("是新開", res.new_item)
    eq("商品序 = 最大3 + 1", res.item_seq, 4)
    eq("款式從 01 起", res.style_seq, 1)
    used_items = {c[5:9] for c, _ in REAL if c[2:5] == "006"}
    check("沒有落在 AS 既有的商品序上", f"{res.item_seq:04d}" not in used_items,
          f"{res.item_seq:04d} 撞到 {used_items}")


def test_append_only_reuse():
    print("\n[9] append-only：既有規格原文沿用舊碼、新原文才發新號")
    ex = [ExistingRow("AA0060004010001", "AAS20_x_色號01", "色號01", ""),
          ExistingRow("AA0060004010002", "AAS20_x_色號02", "色號02", "")]
    res = allocate("AAS20", [("色號01", ""), ("色號09", "")], ex, CTX)
    eq("既有沿用", res.allocations[0].sku_code, "AA0060004010001")
    eq("新原文拿 0003（最大+1，不補空號）", res.allocations[1].sku_code,
       "AA0060004010003")
    eq("沿用1／新發1", (res.reused, res.created), (1, 1))


def test_color_pads_to_four():
    print("\n[10] ⚠️ 顏色序一律補到 4 碼（既有 55 列 5 碼的已由 Edwin 刪除）")
    specs = [(f"色號{i:02d}", "") for i in range(1, 13)]
    res = allocate("AAS20", specs, [], CTX)
    codes = [a.sku_code for a in res.allocations]
    eq("全部 15 碼", {len(c) for c in codes}, {15})
    eq("第 10 個顏色是 0010 不是 00010", codes[9][-4:], "0010")
    eq("第 12 個", codes[11][-4:], "0012")


def test_spec_matched_by_original_text():
    print("\n[11] 比對鍵是 1688 原文（簡體），不是我們取的繁體名")
    ex = [ExistingRow("AA0060004010001", "AAS20_x_黑", "黑色", "")]
    r1 = allocate("AAS20", [("黑色", "")], ex, CTX)
    eq("原文相同 → 沿用", r1.allocations[0].sku_code, "AA0060004010001")
    r2 = allocate("AAS20", [("黑", "")], ex, CTX)
    check("原文不同 → 發新號（證明比對的是原文）", r2.created == 1)


if __name__ == "__main__":
    print("=" * 56)
    print("Nail SKU 品號生成器　回歸測試")
    print("=" * 56)
    for fn in (test_parse, test_context_from_real_data, test_build_matches_real_codes,
               test_unknown_brand_raises, test_new_product_gets_max_plus_one,
               test_no_spec_product_gets_color_0000, test_existing_code_continues_style,
               test_new_code_never_lands_on_existing_item, test_append_only_reuse,
               test_color_pads_to_four, test_spec_matched_by_original_text):
        fn()
    print("\n" + "=" * 56)
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
        sys.exit(1)
    print("✅ 全部通過")
