"""正式新品 → 1-1 商品主表「_待貼新品」暫存分頁產生器。

哲學同 inventory-sync 的 _raw_import：機器只寫暫存分頁，正表（商品表/SKU表）
由人複製貼上合併——1-1 是全系統地基，不給外部系統直接寫入；商品編號本來就要
人給，讓人介入發生在「貼上」而非「事後修改」。

分頁版型（上下兩區塊，各自鏡射目標分頁欄序、都從 A 欄對齊）：
  上區塊 → 貼到「商品表」：一商品一列，欄序 A~U 與商品表相同。
  下區塊 → 貼到「SKU表」：一規格一列，欄序 A~P 與 SKU表相同。
  區塊右側外掛「(勿貼)」輔助欄：1688ID／名單編號／規格顯示，貼上時不要選進去。

機器填：規格一/二（1688 原文逐字，cart_adder 拿去頁面比對用，絕不可轉繁）、
        代表網址（正規化 offer/{id}.html）、品名（AI 繁體簡稱）、幣別、
        成本/廠商（抓得到才填——現行抓取器價格覆蓋率低、廠商名未實作，缺就留空）。
人填（黃底）：商品編號、蝦皮售價、特殊訂貨%（商品表）；ERP品號、標籤、安全存量（SKU表）。
公式欄留白：商品表 F/H/I/R~U、SKU表 K/O/P 都是整欄陣列公式，貼上後自動長出。

SKU 品名 = `編號_品名_規格`，編號人補完後由 B 欄輔助公式自動組好 →
貼到 SKU表 時用「選擇性貼上→僅貼上值」。
"""
from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

STAGING_TAB = "_待貼新品"

# 目標分頁表頭（2026-08-20 三家逐欄比對一致；改欄前先跑 verify_headers）
PRODUCT_HEADERS = ["商品編號", "分類", "子分類", "品名", "成本", "台幣成本", "蝦皮售價",
                   "蝦皮毛利率", "綜合毛利率", "特殊訂貨%", "廠商", "代表網址", "狀態",
                   "績效標記", "標籤", "備註", "款式關鍵字", "目標ROAS", "安全ROAS",
                   "變動毛利率", "廣告狀態"]
SKU_HEADERS = ["品號", "品名", "分類", "標籤", "狀態", "進項成本", "幣別", "安全存量",
               "裝箱數/訂貨倍數", "選項註記", "1688網址", "1688規格一", "1688規格二",
               "備註", "廠商", "對應檢查"]

# 人填欄（0-based index，資料列上黃底）
PRODUCT_HUMAN_COLS = [0, 6, 9]        # A 商品編號 / G 蝦皮售價 / J 特殊訂貨%
SKU_HUMAN_COLS = [0, 3, 7]            # A 品號 / D 標籤 / H 安全存量
# 公式欄（貼上後由正表整欄陣列公式自動長出，這裡一律留白）
PRODUCT_FORMULA_COLS = [5, 7, 8, 17, 18, 19, 20]   # F/H/I/R/S/T/U
SKU_FORMULA_COLS = [10, 14, 15]                     # K/O/P

YELLOW = {"red": 1.0, "green": 0.95, "blue": 0.6}
GREY_TEXT = {"red": 0.55, "green": 0.55, "blue": 0.55}
BLUE_HDR = {"red": 0.85, "green": 0.9, "blue": 0.97}


class StagingNotEmpty(Exception):
    """_待貼新品 還留著上一批沒貼走的資料（force=True 才覆蓋）。"""


def _clean_url(item_id: str) -> str:
    return f"https://detail.1688.com/offer/{item_id}.html"


def _size_original_map(product_data: dict) -> dict[str, str]:
    """normalized 尺碼 key → 1688 頁面原文（規格二必須逐字原文才能比對）。

    key 來源是 Claude 的 size_labels（'S'/'M'…），原文長相不定：
    'S【88-98斤】'（括號）或 'S 适合75-105斤'（空格）→ 取開頭字母數字 token 當 key；
    純中文尺碼（均码）取到空 token 時退回 _clean_size_key。大小寫不敏感。
    """
    from scraper.copywriter import _clean_size_key
    out: dict[str, str] = {}
    for orig in product_data.get("sizes") or []:
        s = str(orig).strip()
        m = re.match(r"^[A-Za-z0-9]+", s)
        key = (m.group(0) if m else _clean_size_key(s)).upper()
        out.setdefault(key, s)
    return out


def _sku_price(product_data: dict, size_orig: str) -> str:
    """該規格的 1688 價：size_stock 有就用，退 price_cny，再沒有留空（人補）。"""
    info = (product_data.get("size_stock") or {}).get(size_orig)
    if isinstance(info, dict) and (info.get("price") or 0) > 0:
        return str(info["price"])
    p = product_data.get("price_cny") or 0
    return str(p) if p > 0 else ""


def build_blocks(prepared: list[dict]) -> tuple[list[list[str]], list[dict]]:
    """prepared（batch_pipeline2._prepare_product 的輸出）→ (商品列, SKU列描述)。

    SKU 列描述帶 owner_idx（第幾個商品）供寫入時組 B 欄公式（直接引用上區塊儲存格）。
    """
    products: list[list[str]] = []
    skus: list[dict] = []
    for idx, p in enumerate(prepared):
        pd = p["product_data"]
        cfg = p.get("config", {})
        meta = p.get("_meta", {})
        item_id = str(meta.get("item_id", pd.get("item_id", "")))
        category = str(cfg.get("category", ""))
        short_name = (p.get("ai_content", {}) or {}).get("product_short_name") or pd.get("title", "")
        price_cny = pd.get("price_cny") or 0

        row = [""] * len(PRODUCT_HEADERS)
        row[1] = category                                   # B 分類
        row[3] = short_name                                 # D 品名
        row[4] = str(price_cny) if price_cny > 0 else ""    # E 成本（抓得到才填）
        row[10] = str(pd.get("shop_name") or "")            # K 廠商（抓得到才填）
        row[11] = _clean_url(item_id)                       # L 代表網址
        products.append(row)

        variants = p.get("variants", {})
        tier1 = variants.get("規格1_顏色") or []
        tier2 = variants.get("規格2_尺碼") or []
        size_map = _size_original_map(pd)

        if tier2:
            for t1 in tier1:
                for t2 in tier2:
                    orig_size = size_map.get(str(t2["size"]).upper(), t2["size"])
                    skus.append({
                        "owner_idx": idx, "item_id": item_id, "category": category,
                        "spec1": str(t1.get("src_1688", "")), "spec2": orig_size,
                        "display": f"{t1.get('color', '')}_{t2['size']}",
                        "price": _sku_price(pd, orig_size),
                    })
        else:
            for t1 in tier1:
                skus.append({
                    "owner_idx": idx, "item_id": item_id, "category": category,
                    "spec1": str(t1.get("src_1688", "")), "spec2": "",
                    "display": str(t1.get("color", "")),
                    "price": str(price_cny) if price_cny > 0 else "",
                })
    return products, skus


def staging_has_leftover(shop: str, sa_json: str | Path | None = None) -> bool:
    """_待貼新品 是否還留著上一批資料（GUI 開跑前預檢，避免在背景執行緒跳對話框）。"""
    import gspread
    from google.oauth2.service_account import Credentials

    from scraper.master_reader import SHOP_SHEETS, resolve_sa_json

    sa = resolve_sa_json(sa_json)
    creds = Credentials.from_service_account_file(
        str(sa), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    try:
        ws = gc.open_by_key(SHOP_SHEETS[str(shop).lower()]).worksheet(STAGING_TAB)
    except gspread.WorksheetNotFound:
        return False
    vals = ws.get_all_values()
    return any(cell.strip() for r in vals[2:] for cell in r)


def write_staging(shop: str, prepared: list[dict], force: bool = False,
                  sa_json: str | Path | None = None) -> dict:
    """把 prepared 商品寫進該賣場 1-1 的 _待貼新品 分頁。

    分頁若還有上一批資料且 force=False → 丟 StagingNotEmpty（不默默清掉人還沒貼走的東西）。
    機器分頁採「刪掉重建」而非 clear()——gspread clear 只清值不清格式（#S163），
    重建才不會殘留上一批的黃底/格式。
    """
    import gspread
    from google.oauth2.service_account import Credentials

    from scraper.master_reader import SHOP_SHEETS, resolve_sa_json

    if not prepared:
        return {"written": 0}
    sheet_id = SHOP_SHEETS[str(shop).lower()]
    sa = resolve_sa_json(sa_json)
    creds = Credentials.from_service_account_file(
        str(sa), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)

    old = None
    try:
        old = sh.worksheet(STAGING_TAB)
    except gspread.WorksheetNotFound:
        pass
    if old is not None:
        vals = old.get_all_values()
        has_data = any(cell.strip() for r in vals[2:] for cell in r)  # 前兩列是說明/表頭
        if has_data and not force:
            raise StagingNotEmpty(
                f"「{STAGING_TAB}」還留著上一批（{len(vals)} 列）。先貼走/清空，或選擇覆蓋。")

    products, skus = build_blocks(prepared)

    # ── 版面座標（1-based）──
    b1_note, b1_hdr, b1_first = 1, 2, 3
    b1_last = b1_first + len(products) - 1
    b2_note = b1_last + 2                      # 空一列
    b2_hdr, b2_first = b2_note + 1, b2_note + 2
    b2_last = b2_first + len(skus) - 1

    n_rows = b2_last + 2
    n_cols = max(len(PRODUCT_HEADERS), len(SKU_HEADERS)) + 3   # +輔助欄
    if old is not None:
        sh.del_worksheet(old)
    ws = sh.add_worksheet(STAGING_TAB, rows=n_rows, cols=n_cols)

    def a1(col0: int, row: int) -> str:
        return gspread.utils.rowcol_to_a1(row, col0 + 1)

    # ── 上區塊：商品表 ──
    rows1: list[list[str]] = []
    rows1.append([f"■ 上區塊 → 貼到「商品表」最下方（選 A{b1_first}:U{b1_last} 整塊複製貼上；"
                  "黃底＝人工必填；F/H/I/R~U 是陣列公式貼上後自動長出；(勿貼) 欄不要選進去）"])
    rows1.append(PRODUCT_HEADERS + ["1688ID(勿貼)", "名單編號(參考,勿貼)"])
    for i, row in enumerate(products):
        meta = prepared[i].get("_meta", {})
        rows1.append(row + [str(meta.get("item_id", "")), str(meta.get("code", ""))])

    # ── 下區塊：SKU表 ──
    rows2: list[list[str]] = []
    rows2.append([f"■ 下區塊 → 貼到「SKU表」最下方：先把上區塊 A 欄商品編號補齊 → B 品名自動組好 → "
                  f"選 A{b2_first}:P{b2_last}「選擇性貼上→僅貼上值」；K/O/P 是陣列公式會自動長出"])
    rows2.append(SKU_HEADERS + ["1688ID(勿貼)", "規格顯示(勿貼)"])
    for j, s in enumerate(skus):
        owner_row = b1_first + s["owner_idx"]
        disp_cell = a1(len(SKU_HEADERS) + 1, b2_first + j)     # 規格顯示輔助欄
        formula = (f'=IF($A${owner_row}="","",'
                   f'$A${owner_row}&"_"&$D${owner_row}&"_"&{disp_cell})')
        row = [""] * len(SKU_HEADERS)
        row[1] = formula                    # B 品名（編號_品名_規格，等人補編號）
        row[2] = s["category"]              # C 分類
        row[5] = s["price"]                 # F 進項成本（抓得到才填；⚠️ 包裝品要換算單個）
        row[6] = "人民幣"                    # G 幣別（照 SKU 表既有慣例）
        row[11] = s["spec1"]                # L 規格一（1688 原文逐字）
        row[12] = s["spec2"]                # M 規格二（1688 原文逐字）
        rows2.append(row + [s["item_id"], s["display"]])

    ws.update(f"A{b1_note}", rows1, value_input_option="USER_ENTERED")
    ws.update(f"A{b2_note}", rows2, value_input_option="USER_ENTERED")

    # ── 格式（批次，避免 429）──
    def col_range(col0: int, first: int, last: int) -> str:
        return f"{a1(col0, first)}:{a1(col0, last)}"

    fmt: list[tuple[list[str], dict]] = []
    hdr_ranges = [f"A{b1_hdr}:{a1(len(PRODUCT_HEADERS) + 1, b1_hdr)}",
                  f"A{b2_hdr}:{a1(len(SKU_HEADERS) + 1, b2_hdr)}"]
    fmt.append((hdr_ranges, {"backgroundColor": BLUE_HDR, "textFormat": {"bold": True}}))
    if products:
        fmt.append(([col_range(c, b1_first, b1_last) for c in PRODUCT_HUMAN_COLS],
                    {"backgroundColor": YELLOW}))
        fmt.append(([col_range(len(PRODUCT_HEADERS), b1_first, b1_last),
                     col_range(len(PRODUCT_HEADERS) + 1, b1_first, b1_last)],
                    {"textFormat": {"foregroundColor": GREY_TEXT}}))
    if skus:
        fmt.append(([col_range(c, b2_first, b2_last) for c in SKU_HUMAN_COLS],
                    {"backgroundColor": YELLOW}))
        fmt.append(([col_range(len(SKU_HEADERS), b2_first, b2_last),
                     col_range(len(SKU_HEADERS) + 1, b2_first, b2_last)],
                    {"textFormat": {"foregroundColor": GREY_TEXT}}))
    for ranges, style in fmt:
        ws.format(ranges, style)

    logger.info(f"[{shop}] {STAGING_TAB} 已寫入：{len(products)} 商品 / {len(skus)} SKU 列")
    return {"written": len(products), "sku_rows": len(skus), "tab": STAGING_TAB,
            "sheet_id": sheet_id}
