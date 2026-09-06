"""_待貼新品 產生器回歸測試（免 pytest，直接 `python3 tests/test_master_staging.py`）。

只測純函式（build_blocks / MasterContext / is_preorder），不連網。
守住的重點：預購與正式的分流、機器該填的欄真的有填、原文逐字不被動到、
以及 `J 特殊訂貨%` 必須是 1 不是 100。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.master_staging import (  # noqa: E402
    PREORDER_SAFETY_STOCK, PREORDER_TAG, PRODUCT_HEADERS, SKU_HEADERS,
    HeaderMismatch, MasterContext, build_blocks, is_preorder, verify_headers,
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


# ── 假的既有 1-1 資料（欄序照線上）──
PRODUCT_ROWS = [
    ["H-b7", "H.貼身衣褲", "b. 內衣"],
    ["H-c2", "H.貼身衣褲", "c. 內褲"],
    ["P-a101", "P.其他", "a.防曬相關"],
]
SKU_ROWS = [
    ["BH0030002000102", "H-c2_蝴蝶結素色三角褲_淺灰,L", "女性周邊_H.內衣"] + [""] * 8
    + ["067-浅灰", "L"],
    ["BH0030002000603", "H-c2_蝴蝶結素色三角褲_杏色,XL", "女性周邊_H.內衣"] + [""] * 8
    + ["067-杏色", "XL"],
    ["BP0010101010001", "P-a101_修身防曬外套_黑,M", "女性周邊_P.功能性"] + [""] * 8
    + ["黑", "M"],
]
CTX = MasterContext(PRODUCT_ROWS, SKU_ROWS)


_NODEFAULT = object()


def _prepared(code, demand="", tag="", subcat="", price=399, colors=None,
              sizes=_NODEFAULT, cost=12.5, supplier="某某廠"):
    """組一筆 batch_pipeline2 的 prepared。sizes=[] 代表單軸商品（沒有第二軸）。"""
    if colors is None:
        colors = [{"color": "杏色", "src_1688": "067-杏色"}]
    if sizes is _NODEFAULT:
        sizes = [{"size": "XL"}]
    variants = {"規格1_顏色": colors}
    if sizes:
        variants["規格2_尺碼"] = sizes
    return {
        # sizes 的原文要與既有 SKU表 M 欄一致（線上 H-c2 的 M 就是純 "XL"），
        # 否則比對不到會發新號——這正是「比對鍵必須是原文」的實際後果。
        "product_data": {"item_id": "953732723854", "price_cny": cost,
                         "shop_name": supplier, "sizes": ["XL"],
                         "title": "原始標題"},
        "ai_content": {"product_short_name": "蝴蝶結素色三角褲"},
        "variants": variants,
        "config": {"selling_price": price, "demand": demand, "tag": tag,
                   "subcategory": subcat, "code": code},
        "_meta": {"code": code, "item_id": "953732723854"},
    }


def test_is_preorder():
    print("\n[1] 預購判定")
    check("『預購』→ True", is_preorder("預購"))
    check("『預購(試單)』→ True", is_preorder("預購(試單)"))
    check("『現貨』→ False", not is_preorder("現貨"))
    check("空白 → False", not is_preorder(""))


def test_headers_are_the_three_shop_contract():
    print("\n[2] 表頭＝三家共通契約（商品表 A~U 21 欄 / SKU表 A~P 16 欄）")
    eq("商品表 21 欄", len(PRODUCT_HEADERS), 21)
    eq("SKU表 只到 P（16 欄）", len(SKU_HEADERS), 16)
    eq("最後一欄是對應檢查", SKU_HEADERS[-1], "對應檢查")
    check("⚠️ 不可含單件重量(g)——那是 Lady 專屬的 Q 欄，Nail Q 是到貨前庫存",
          "單件重量(g)" not in SKU_HEADERS)


class _FakeWS:
    def __init__(self, hdr): self.hdr = hdr
    def get(self, rng): return [self.hdr]


class _FakeSH:
    def __init__(self, prod, sku): self.m = {"商品表": _FakeWS(prod), "SKU表": _FakeWS(sku)}
    def worksheet(self, t): return self.m[t]


def test_header_mismatch_aborts():
    print("\n[2b] 表頭不符一定要中止（貼錯欄不會報錯，是最貴的靜默錯）")
    ok = _FakeSH(list(PRODUCT_HEADERS), list(SKU_HEADERS))
    try:
        verify_headers(ok, "lady"); check("契約相符 → 通過", True)
    except HeaderMismatch as e:
        check("契約相符 → 通過", False, str(e))

    # 三家 Q 之後不同，但契約範圍相同 → 必須通過（這正是修這題的原因）
    nail = _FakeSH(list(PRODUCT_HEADERS),
                   list(SKU_HEADERS) + ["0824到貨前庫存", "AI建議訂購", "AI建議安全存量", "銷速來源"])
    try:
        verify_headers(nail, "nail"); check("Nail 多 4 欄仍通過（只驗 A~P）", True)
    except HeaderMismatch as e:
        check("Nail 多 4 欄仍通過（只驗 A~P）", False, str(e))

    bad = _FakeSH(list(PRODUCT_HEADERS), ["品號", "品名", "分類", "標籤", "狀態", "進項成本",
                                          "幣別", "安全存量", "裝箱數/訂貨倍數", "選項註記",
                                          "1688網址", "1688規格一", "1688規格二", "備註",
                                          "廠商", "❌被改掉的欄名"])
    try:
        verify_headers(bad, "nail"); check("契約被改動 → 必須拋錯", False, "竟然通過了")
    except HeaderMismatch as e:
        check("契約被改動 → 必須拋錯", True)
        check("錯誤訊息要指出是哪一欄", "第16欄(P)" in str(e), str(e)[:120])

    short = _FakeSH(list(PRODUCT_HEADERS), SKU_HEADERS[:10])
    try:
        verify_headers(short, "x"); check("欄數不足 → 必須拋錯", False)
    except HeaderMismatch:
        check("欄數不足 → 必須拋錯", True)


def test_category_derivation():
    print("\n[3] 分類由商品編號字母推導（不用人再填一次）")
    eq("H-c2 → 商品表 B", CTX.product_category("H-c2"), "H.貼身衣褲")
    eq("H-c2 → 商品表 C", CTX.product_subcategory("H-c2"), "c. 內褲")
    eq("H-b7 → 子分類不同", CTX.product_subcategory("H-b7"), "b. 內衣")
    eq("H-c2 → SKU表 C（另一套字串）", CTX.sku_category("H-c2"), "女性周邊_H.內衣")
    eq("P-a101 → SKU表 C", CTX.sku_category("P-a101"), "女性周邊_P.功能性")
    eq("沒見過的字母 → 空字串（不亂猜）", CTX.product_category("Z-a1"), "")


def test_product_row_machine_filled():
    print("\n[4] 商品表列：機器該填的都填了")
    products, _ = build_blocks("lady", [_prepared("H-c2")], CTX)
    r = products[0]
    eq("A 商品編號", r[0], "H-c2")
    eq("B 分類（推導）", r[1], "H.貼身衣褲")
    eq("C 子分類（推導）", r[2], "c. 內褲")
    eq("D 品名", r[3], "蝴蝶結素色三角褲")
    eq("E 成本", r[4], "12.5")
    eq("G 蝦皮售價", r[6], "399")
    eq("K 廠商", r[10], "某某廠")
    eq("L 代表網址（正規化、無垃圾參數）", r[11],
       "https://detail.1688.com/offer/953732723854.html")
    for idx, name in [(5, "F 台幣成本"), (7, "H 毛利率"), (8, "I 綜合毛利率"),
                      (17, "R 目標ROAS"), (20, "U 廣告狀態")]:
        eq(f"公式欄留白：{name}", r[idx], "")


def test_special_order_ratio_is_one_not_hundred():
    print("\n[5] ⚠️ J 特殊訂貨% 必須是 1（PERCENT 格式），寫 100 會膨脹 100 倍")
    products, _ = build_blocks("lady", [_prepared("H-c2")], CTX)
    eq("J = 1", products[0][9], 1)
    check("絕不是 100", products[0][9] != 100)


def test_subcategory_from_list_wins():
    print("\n[6] 子分類：名單有填優先，沒填才推導")
    products, _ = build_blocks("lady", [_prepared("H-c2", subcat="z. 手動指定")], CTX)
    eq("名單填了就用名單的", products[0][2], "z. 手動指定")


def test_preorder_branch():
    print("\n[7] 預購分支：標籤 #PO_Sale + 安全存量 200")
    _, skus = build_blocks("lady", [_prepared("H-c2", demand="預購", tag="#LM_1st")], CTX)
    eq("標籤蓋成 #PO_Sale（名單的標籤不採用）", skus[0]["tag"], PREORDER_TAG)
    check("標成預購", skus[0]["preorder"])


def test_formal_branch():
    print("\n[8] 正式分支：標籤用名單的，安全存量留空給人填")
    _, skus = build_blocks("lady", [_prepared("H-c2", demand="現貨", tag="#LM_1st")], CTX)
    eq("標籤＝名單的", skus[0]["tag"], "#LM_1st")
    check("不是預購", not skus[0]["preorder"])


def test_sku_row_fields():
    print("\n[9] SKU 列：品號用規則生成、品名格式正確、原文逐字")
    _, skus = build_blocks("lady", [_prepared("H-c2", demand="預購")], CTX)
    s = skus[0]
    eq("品號沿用既有（杏色0006 + XL03）", s["sku_code"], "BH0030002000603")
    eq("品名＝編號_品名_規格", s["name"], "H-c2_蝴蝶結素色三角褲_杏色,XL")
    eq("L 規格一＝1688 簡體原文，未轉繁", s["spec1"], "067-杏色")
    eq("C 分類（推導）", s["category"], "女性周邊_H.內衣")


def test_new_color_gets_new_code():
    print("\n[10] 新顏色 → 發新號，不撞既有")
    p = _prepared("H-c2", demand="預購",
                  colors=[{"color": "新色", "src_1688": "067-新色"}])
    _, skus = build_blocks("lady", [p], CTX)
    # 既有 H-c2 顏色序最大 = 6（杏色）→ 新色拿 0007
    eq("新色拿 0007", skus[0]["sku_code"], "BH0030002000703")
    check("不與既有品號相同",
          skus[0]["sku_code"] not in {"BH0030002000102", "BH0030002000603"})


def test_unsupported_shop_leaves_blank_not_wrong_code():
    print("\n[11] 未支援賣場：品號留空給人補，**不可**產出看似合法的錯碼")
    _, skus = build_blocks("nail", [_prepared("H-c2", demand="預購")], CTX)
    eq("品號留空", skus[0]["sku_code"], "")
    check("其餘欄位照樣填好（不整批失敗）", skus[0]["spec1"] == "067-杏色")


def test_bad_code_does_not_kill_batch():
    print("\n[12] 商品編號格式錯 → 只有該支品號留空，不影響整批")
    ps = [_prepared("CHE"), _prepared("H-c2", demand="預購")]
    products, skus = build_blocks("lady", ps, CTX)
    eq("兩支商品都有列", len(products), 2)
    eq("格式錯的品號留空", skus[0]["sku_code"], "")
    eq("正常的照樣生成", skus[-1]["sku_code"], "BH0030002000603")


def test_single_axis_product():
    print("\n[13] 單軸商品（只有顏色）")
    p = _prepared("H-c2", demand="預購",
                  colors=[{"color": "杏色", "src_1688": "067-杏色"}], sizes=[])
    _, skus = build_blocks("lady", [p], CTX)
    eq("規格二空", skus[0]["spec2"], "")
    eq("品名不帶逗號規格", skus[0]["name"], "H-c2_蝴蝶結素色三角褲_杏色")


if __name__ == "__main__":
    print("=" * 56)
    print("_待貼新品 產生器回歸測試")
    print("=" * 56)
    for fn in (test_is_preorder, test_headers_are_the_three_shop_contract,
               test_header_mismatch_aborts, test_category_derivation,
               test_product_row_machine_filled, test_special_order_ratio_is_one_not_hundred,
               test_subcategory_from_list_wins, test_preorder_branch, test_formal_branch,
               test_sku_row_fields, test_new_color_gets_new_code,
               test_unsupported_shop_leaves_blank_not_wrong_code,
               test_bad_code_does_not_kill_batch, test_single_axis_product):
        fn()
    print("\n" + "=" * 56)
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
        sys.exit(1)
    print("✅ 全部通過")
