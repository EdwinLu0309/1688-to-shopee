"""SKU 品號生成器回歸測試（免 pytest，直接 `python3 tests/test_sku_code.py`）。

守住三件事：①規則本身算得對（用線上實測樣本對答案）②append-only 不重編、不回收
③未支援的賣場一定拋錯而不是產出看似合法的碼。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.sku_code import (  # noqa: E402
    AllocResult, BadProductCode, ExistingRow, UnsupportedShop,
    allocate, build_code, collect_existing, parse_product_code,
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


# ── 線上真實樣本（2026-08-27 讀 Lady 1-1）──
# H-c2_蝴蝶結素色三角褲：12 列，顏色序 1/2/5/6/7/9，尺寸 L=02 XL=03
REAL_HC2 = [
    ("BH0030002000102", "H-c2_蝴蝶結素色三角褲_淺灰,L", "067-浅灰", "L"),
    ("BH0030002000103", "H-c2_蝴蝶結素色三角褲_淺灰,XL", "067-浅灰", "XL"),
    ("BH0030002000202", "H-c2_蝴蝶結素色三角褲_紫色,L", "067-卡其", "L"),
    ("BH0030002000203", "H-c2_蝴蝶結素色三角褲_紫色,XL", "067-卡其", "XL"),
    ("BH0030002000502", "H-c2_蝴蝶結素色三角褲_灰藍,L", "067-灰蓝", "L"),
    ("BH0030002000503", "H-c2_蝴蝶結素色三角褲_灰藍,XL", "067-灰蓝", "XL"),
    ("BH0030002000602", "H-c2_蝴蝶結素色三角褲_杏色,L", "067-杏色", "L"),
    ("BH0030002000603", "H-c2_蝴蝶結素色三角褲_杏色,XL", "067-杏色", "XL"),
    ("BH0030002000702", "H-c2_蝴蝶結素色三角褲_淺豆沙,L", "067-浅豆沙", "L"),
    ("BH0030002000703", "H-c2_蝴蝶結素色三角褲_淺豆沙,XL", "067-浅豆沙", "XL"),
    ("BH0030002000902", "H-c2_蝴蝶結素色三角褲_墨綠,L", "067-墨绿", "L"),
    ("BH0030002000903", "H-c2_蝴蝶結素色三角褲_墨綠,XL", "067-墨绿", "XL"),
]
EXISTING_HC2 = [ExistingRow(a, b, c, d) for a, b, c, d in REAL_HC2]


def test_parse():
    print("\n[1] 商品編號解析")
    pc = parse_product_code("H-c2")
    eq("H-c2 → cat/sub/model", (pc.cat, pc.sub, pc.model), ("H", "c", 2))
    eq("c 的字母序 = 3", pc.sub_seq, 3)
    eq("P-a101 → 款號 101", parse_product_code("P-a101").model, 101)
    eq("B-b9 → 子分類序 2", parse_product_code("B-b9").sub_seq, 2)
    try:
        parse_product_code("CHE")           # Nail 的品名前綴，不是商品編號
        check("非法編號要拋錯", False)
    except BadProductCode:
        check("非法編號要拋錯", True)


def test_build():
    print("\n[2] 組碼（對線上實測值）")
    eq("H-c2 杏色(6) XL(3)", build_code("lady", "H-c2", 6, 3), "BH0030002000603")
    eq("H-c2 淺灰(1) L(2)", build_code("lady", "H-c2", 1, 2), "BH0030002000102")
    eq("長度固定 15", len(build_code("lady", "P-a101", 1, 1)), 15)


def test_unsupported_shop():
    print("\n[3] 未支援賣場必須拋錯（不可硬套 Lady 規則）")
    for shop in ("nail", "baby"):
        try:
            build_code(shop, "H-c2", 1, 1)
            check(f"{shop} 要拋 UnsupportedShop", False, "→ 竟然產出了碼")
        except UnsupportedShop:
            check(f"{shop} 要拋 UnsupportedShop", True)


def test_reuse_all():
    print("\n[4] 全部既有 → 原碼奉還，一個都不重編")
    specs = [(r.spec1, r.spec2) for r in EXISTING_HC2]
    res = allocate("lady", "H-c2", specs, EXISTING_HC2)
    eq("沿用數", res.reused, 12)
    eq("新發數", res.created, 0)
    eq("碼與既有完全一致",
       [a.sku_code for a in res.allocations], [r.sku_code for r in EXISTING_HC2])


def test_new_color_appends():
    print("\n[5] 新顏色 → max+1，不回收刪掉的號（append-only 鐵律）")
    # 既有最大顏色序 = 9（墨綠）；空著的 3/4/8 是「刪掉的」，絕不可撿回來
    specs = [("067-浅灰", "L"), ("067-新色A", "L"), ("067-新色B", "XL")]
    res = allocate("lady", "H-c2", specs, EXISTING_HC2)
    codes = [a.sku_code for a in res.allocations]
    eq("既有淺灰沿用", codes[0], "BH0030002000102")
    eq("新色A 拿 0010 不是 0003", codes[1], "BH0030002001002")
    eq("新色B 拿 0011", codes[2], "BH0030002001103")
    eq("沿用1／新發2", (res.reused, res.created), (1, 2))
    check("沒有任何新碼落在既有碼上", not (set(codes[1:]) & {r.sku_code for r in EXISTING_HC2}))


def test_new_size_appends():
    print("\n[6] 新尺寸 → 尺寸序 max+1（既有最大 03）")
    res = allocate("lady", "H-c2", [("067-杏色", "2XL")], EXISTING_HC2)
    eq("杏色沿用 0006、尺寸新發 04", res.allocations[0].sku_code, "BH0030002000604")


def test_spec_is_matched_by_original_text():
    print("\n[7] 比對鍵是 1688 原文，不是品名裡的繁體名")
    # 「紫色」是我們取的名，1688 原文是 067-卡其 → 用原文才找得到既有碼
    r1 = allocate("lady", "H-c2", [("067-卡其", "L")], EXISTING_HC2)
    eq("用原文 067-卡其 → 沿用 0002", r1.allocations[0].sku_code, "BH0030002000202")
    r2 = allocate("lady", "H-c2", [("紫色", "L")], EXISTING_HC2)
    check("用繁體名『紫色』→ 認不得，會發新號（證明比對鍵是原文）",
          r2.allocations[0].sku_code != "BH0030002000202" and r2.created == 1)


def test_whitespace_normalized_not_translated():
    print("\n[8] 原文只壓空白、不改字")
    res = allocate("lady", "H-c2", [("067-浅灰 ", "L")], EXISTING_HC2)
    eq("多餘空白不影響比對", res.allocations[0].sku_code, "BH0030002000102")
    eq("仍算沿用", res.reused, 1)


def test_single_axis():
    print("\n[9] 單軸商品（無第二層選項）尺寸序 = 00")
    res = allocate("lady", "B-b9", [("淺咖", ""), ("米色", "")], [])
    eq("第一個顏色", res.allocations[0].sku_code, "BB0020009000100")
    eq("第二個顏色", res.allocations[1].sku_code, "BB0020009000200")


def test_new_product_from_scratch():
    print("\n[10] 全新商品：依「要進貨販售的順序」連號（不對應 1688 頁面位置）")
    specs = [("067-杏色", "M"), ("067-杏色", "L"), ("067-墨绿", "M")]
    res = allocate("lady", "H-c9", specs, [])
    eq("杏色=0001 M=01", res.allocations[0].sku_code, "BH0030009000101")
    eq("杏色 L=02", res.allocations[1].sku_code, "BH0030009000102")
    eq("墨绿=0002 沿用 M=01", res.allocations[2].sku_code, "BH0030009000201")


def test_collect_existing():
    print("\n[11] 從 SKU 表原始列挑出該商品（靠品名前綴，同 K/O/P 公式的解析法）")
    rows = [
        ["BH0030002000102", "H-c2_蝴蝶結素色三角褲_淺灰,L"] + [""] * 9 + ["067-浅灰", "L"],
        ["BH0030003000101", "H-c3_別的商品_黑,M"] + [""] * 9 + ["黑", "M"],
        ["BB0020009010001", "B-b9_奶茶色髮圈_淺咖"] + [""] * 9 + ["", ""],
        ["", ""],                                    # 空列
    ]
    got = collect_existing(rows, "H-c2")
    eq("只挑到 H-c2 一列", [r.sku_code for r in got], ["BH0030002000102"])
    eq("有帶出原文", (got[0].spec1, got[0].spec2), ("067-浅灰", "L"))
    check("H-c3 不會被 H-c2 誤配（編號邊界）", len(collect_existing(rows, "H-c3")) == 1)


def test_legacy_rows_ignored():
    print("\n[12] 不合本規則的舊列不污染配號")
    legacy = EXISTING_HC2 + [ExistingRow("P14AE1_黑色_S", "H-c2_x_黑", "黑", "S")]
    res = allocate("lady", "H-c2", [("067-新色", "L")], legacy)
    eq("仍從 0009 之後發號", res.allocations[0].sku_code, "BH0030002001002")


if __name__ == "__main__":
    print("=" * 56)
    print("SKU 品號生成器回歸測試")
    print("=" * 56)
    for fn in (test_parse, test_build, test_unsupported_shop, test_reuse_all,
               test_new_color_appends, test_new_size_appends,
               test_spec_is_matched_by_original_text,
               test_whitespace_normalized_not_translated, test_single_axis,
               test_new_product_from_scratch, test_collect_existing,
               test_legacy_rows_ignored):
        fn()
    print("\n" + "=" * 56)
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
        sys.exit(1)
    print("✅ 全部通過")
