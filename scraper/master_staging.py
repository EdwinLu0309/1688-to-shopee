"""正式新品／預購新品 → 1-1 商品主表「_待貼新品」暫存分頁產生器。

哲學同 inventory-sync 的 _raw_import：機器只寫暫存分頁，正表（商品表/SKU表）由人複製
貼上合併——1-1 是全系統地基，不給外部系統直接寫入；且本模組尚未經長期實跑驗證，
未驗證的寫入器不該第一個動作就直寫地基。

★2026-08-28 統一架構（正本＝`1688-order/docs/上架訂貨統一架構.md`）：
**預購不再是特例**——預購與正式品都寫進同一張 1-1 SKU 表，靠 D 標籤分流：
預購品標籤固定 `#PO_Sale`，訂貨表 M 訂貨量試算會排除它（比照既有的 `#CL_Sale`），
所以預購品不會被當成要備庫存的品，但照樣能走「填 O → R 自動 TRUE → 加購 → 核對 → 下單」。

分頁版型（上下兩區塊，各自鏡射目標分頁欄序、都從 A 欄對齊）：
  上區塊 → 貼到「商品表」：一商品一列，欄序 A~U 與商品表相同。
  下區塊 → 貼到「SKU表」：一規格一列，欄序 A~P 與 SKU表相同。
  ⚠️ **只寫到 P**——Q 之後三家完全不同（Lady 重量／Nail 到貨前庫存／Baby AI建議），
     寫死一份拿去跑別家會貼錯欄且不報錯。每次執行都先 `verify_headers` 驗契約，不符即中止。
  區塊右側外掛「(勿貼)」輔助欄：1688ID／名單編號／規格顯示，貼上時不要選進去。

機器填（2026-08-28 起人工介入降到 0 欄）：
  商品表 A 商品編號（AI 名單給）／B 分類·C 子分類（名單有填優先，否則依商品編號字母
  從既有資料推導）／D 品名／G 蝦皮售價（名單）／J 特殊訂貨%／L 代表網址（正規化）
  SKU表 A 品號（`sku_code` 依賣場規則生成，append-only）／B 品名（`編號_品名_規格`，
  直接寫值不用公式）／C 分類（依字母推導）／D 標籤（預購＝`#PO_Sale`，正式＝名單「標籤」欄）
  ／G 幣別／H 安全存量（預購＝200）／L·M 1688 規格一二（**原文逐字，絕不轉繁**）
公式欄留白：商品表 F/H/I/R~U、SKU表 K/O/P 都是正表整欄陣列公式，貼上後自動長出。
黃底＝**機器抓不到、要人補**（成本／廠商；現行抓取器覆蓋率低，見 TODO V1.1）。
SKU 單件重量不在契約範圍內，另由 `1688-order/order/weight_scraper.py` 補。

⚠️ `商品表 J 特殊訂貨%` 在正表是 PERCENT 格式（顯示 100%、實值 1）→ 這裡寫 1 並把該欄
   也設成 PERCENT，正常貼上與「僅貼上值」兩種貼法都不會跑掉。寫 100 會讓當期存量
   膨脹 100 倍且完全不報錯。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

from scraper.sku_code import UnsupportedShop, allocate, collect_existing

STAGING_TAB = "_待貼新品"

# 契約表頭：商品表 A~U（21 欄）、SKU表 A~P（16 欄）——2026-09-07 三家逐欄比對確認一致。
# 三家 Q 之後各不相同（Lady 17 欄／Nail 20／Baby SKU 20·商品表 22），故產出只寫契約範圍。
PRODUCT_HEADERS = ["商品編號", "分類", "子分類", "品名", "成本", "台幣成本", "蝦皮售價",
                   "蝦皮毛利率", "綜合毛利率", "特殊訂貨%", "廠商", "代表網址", "狀態",
                   "績效標記", "標籤", "備註", "款式關鍵字", "目標ROAS", "安全ROAS",
                   "變動毛利率", "廣告狀態"]
# ⚠️ 只到 P（16 欄）＝三家共通的契約範圍。**Q 之後三家完全不同、一律不寫**：
#    Lady Q=單件重量(g)｜Nail Q~T=0824到貨前庫存/AI建議訂購/AI建議安全存量/銷速來源
#    ｜Baby Q~T=AI建議安全存量/差額/建議訂量/銷速來源
#    寫死一份表頭拿去跑別家＝**貼錯欄且完全不報錯**，所以產出只寫 A~P。
SKU_HEADERS = ["品號", "品名", "分類", "標籤", "狀態", "進項成本", "幣別", "安全存量",
               "裝箱數/訂貨倍數", "選項註記", "1688網址", "1688規格一", "1688規格二",
               "備註", "廠商", "對應檢查"]

# 公式欄（貼上後由正表整欄陣列公式自動長出，這裡一律留白）
PRODUCT_FORMULA_COLS = [5, 7, 8, 17, 18, 19, 20]   # F/H/I/R/S/T/U
SKU_FORMULA_COLS = [10, 14, 15]                     # K/O/P
# 機器抓不到就留空、要人補的欄（黃底提示）
PRODUCT_TODO_COLS = [4, 10]                         # E 成本 / K 廠商
SKU_TODO_COLS = [5]                                 # F 進項成本（Q 重量不在契約範圍內）

PREORDER_TAG = "#PO_Sale"          # 預購專屬標籤（比照三家共用的 #CL_Sale）
PREORDER_SAFETY_STOCK = "200"      # 預購品安全存量（蝦皮端庫存也開 200）
SPECIAL_ORDER_RATIO = 1            # J 特殊訂貨%：PERCENT 格式，實值 1 ＝ 顯示 100%

YELLOW = {"red": 1.0, "green": 0.95, "blue": 0.6}
GREY_TEXT = {"red": 0.55, "green": 0.55, "blue": 0.55}
BLUE_HDR = {"red": 0.85, "green": 0.9, "blue": 0.97}


class HeaderMismatch(Exception):
    """線上表頭與程式假設的契約欄不符——**一定要中止，不可照寫**。

    貼錯欄不會有任何錯誤訊息，只會把值寫進意義完全不同的欄位（例如把重量寫進
    Nail 的「0824到貨前庫存」）。同「不報錯的錯」那一類，寧可中止也不要寫。
    """


def verify_headers(sh, shop: str) -> tuple[list[str], list[str]]:
    """讀線上實際表頭，比對契約欄（商品表 A~U／SKU表 A~P）。不符就拋 HeaderMismatch。

    回傳 (商品表實際表頭, SKU表實際表頭) 供呼叫端記錄；產出一律只寫契約範圍。
    """
    prod_hdr = sh.worksheet("商品表").get("A1:Z1")[0]
    sku_hdr = sh.worksheet("SKU表").get("A1:Z1")[0]
    for actual, want, tab in ((prod_hdr, PRODUCT_HEADERS, "商品表"),
                              (sku_hdr, SKU_HEADERS, "SKU表")):
        n = len(want)
        got = [c.strip() for c in actual[:n]]
        if got != want:
            diff = [f"第{i+1}欄({chr(65+i)}) 線上「{g}」≠ 預期「{w}」"
                    for i, (g, w) in enumerate(zip(got, want)) if g != w]
            if len(got) < n:
                diff.append(f"線上只有 {len(got)} 欄、契約需要 {n} 欄")
            raise HeaderMismatch(
                f"[{shop}] 「{tab}」表頭與契約不符，已中止（照寫會貼錯欄且不報錯）：\n  "
                + "\n  ".join(diff[:6]))
    logger.info(f"[{shop}] 表頭契約驗證通過（商品表 A~U／SKU表 A~P；"
                f"線上實際 {len(prod_hdr)}／{len(sku_hdr)} 欄，Q 之後不碰）")
    return prod_hdr, sku_hdr


class StagingNotEmpty(Exception):
    """_待貼新品 還留著上一批沒貼走的資料（force=True 才覆蓋）。"""


def is_preorder(demand: str) -> bool:
    """AI 名單「訂貨需求」欄含「預購」→ 走預購分支。"""
    return "預購" in (demand or "")


def _clean_url(item_id: str) -> str:
    return f"https://detail.1688.com/offer/{item_id}.html"


def _code_letters(product_code: str, shop: str = "lady") -> tuple[str, str]:
    """商品編號 → (大分類字母, 子分類/品牌)。**三家格式不同，不可共用一條正則。**

    Lady/Baby：`H-c2` → ('H', 'c')      有連字號，子分類是單一字母
    Nail    ：`AAS1` → ('A', 'AS')      無連字號，中段是品牌字母（AS/VD/IL…）
    解析不出回 ('','')——回空就讓分類推導留白，不亂猜。
    """
    s = (product_code or "").strip()
    if str(shop).lower() == "nail":
        m = re.fullmatch(r"([A-Za-z])([A-Za-z]+)(\d+)", s)
        return (m.group(1).upper(), m.group(2).upper()) if m else ("", "")
    m = re.match(r"\s*([A-Za-z])\s*-\s*([A-Za-z])", s)
    return (m.group(1).upper(), m.group(2).lower()) if m else ("", "")


class MasterContext:
    """從 1-1 正表讀出來的既有資料：分類對照 + SKU 列（供推導與 append-only 配號）。

    分類推導的理由：`商品表 B 分類`（`H.貼身衣褲`）與 `SKU表 C 分類`（`女性周邊_H.內衣`）
    是兩套不同的字串、彼此推不出來，但**都能由商品編號的分類字母查既有資料得到**
    （實測 Lady：B/H/I/O/P 各對應唯一值）。所以不必要求人再填一次。
    """

    def __init__(self, product_rows: list[list[str]], sku_rows: list[list[str]],
                 shop: str = "lady"):
        self.shop = shop
        self.sku_rows = sku_rows
        cat_by_letter: dict[str, Counter] = defaultdict(Counter)
        sub_by_pair: dict[tuple[str, str], Counter] = defaultdict(Counter)
        sku_cat_by_letter: dict[str, Counter] = defaultdict(Counter)

        for r in product_rows:
            code = (r[0] if r else "").strip()
            letter, sub = _code_letters(code, shop)
            if not letter:
                continue
            if len(r) > 1 and r[1].strip():
                cat_by_letter[letter][r[1].strip()] += 1
            if sub and len(r) > 2 and r[2].strip():
                sub_by_pair[(letter, sub)][r[2].strip()] += 1

        for r in sku_rows:
            if len(r) < 3 or not r[1]:
                continue
            letter, _ = _code_letters(r[1].split("_")[0], shop)
            if letter and r[2].strip():
                sku_cat_by_letter[letter][r[2].strip()] += 1

        # Nail 生碼需要品牌碼/最大商品序/既有款式，一併從同一份資料建好
        self.nail = None
        if str(shop).lower() == "nail":
            from scraper.sku_code_nail import NailContext
            self.nail = NailContext.from_sku_rows(sku_rows)

        self.cat_of = {k: c.most_common(1)[0][0] for k, c in cat_by_letter.items()}
        self.subcat_of = {k: c.most_common(1)[0][0] for k, c in sub_by_pair.items()}
        self.sku_cat_of = {k: c.most_common(1)[0][0] for k, c in sku_cat_by_letter.items()}

    def product_category(self, code: str) -> str:
        return self.cat_of.get(_code_letters(code, self.shop)[0], "")

    def product_subcategory(self, code: str) -> str:
        return self.subcat_of.get(_code_letters(code, self.shop), "")

    def sku_category(self, code: str) -> str:
        return self.sku_cat_of.get(_code_letters(code, self.shop)[0], "")


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


def build_blocks(shop: str, prepared: list[dict],
                 ctx: MasterContext) -> tuple[list[list[str]], list[dict]]:
    """prepared（batch_pipeline2._prepare_product 的輸出）→ (商品列, SKU列描述)。

    需要 ctx（既有 1-1 資料）才能推導分類、並用 append-only 規則配 SKU 品號。
    """
    products: list[list[str]] = []
    skus: list[dict] = []
    for idx, p in enumerate(prepared):
        pd = p["product_data"]
        cfg = p.get("config", {})
        meta = p.get("_meta", {})
        code = str(meta.get("code") or cfg.get("code") or "")
        item_id = str(meta.get("item_id", pd.get("item_id", "")))
        short_name = (p.get("ai_content", {}) or {}).get("product_short_name") or pd.get("title", "")
        price_cny = pd.get("price_cny") or 0
        preorder = is_preorder(str(cfg.get("demand", "")))

        row = [""] * len(PRODUCT_HEADERS)
        row[0] = code                                        # A 商品編號（名單給）
        row[1] = ctx.product_category(code)                  # B 分類（依編號字母推導）
        row[2] = (str(cfg.get("subcategory", "")).strip()    # C 子分類（名單優先）
                  or ctx.product_subcategory(code))
        row[3] = short_name                                  # D 品名
        row[4] = str(price_cny) if price_cny > 0 else ""     # E 成本（抓得到才填）
        # G 蝦皮售價 ＝ **實際成交價（折後）**，不是掛牌價。
        # ⚠️ 這欄餵給 H 蝦皮毛利率 → I 綜合毛利率 → R 目標ROAS / S 安全ROAS。
        #    填掛牌價會讓毛利率虛高（實例：掛牌690/折後345/成本120 → 65% 虛報成 83%），
        #    安全線被算低 → 廣告會被判成「還有空間」而多花錢。
        final = cfg.get("final_price") or 0
        if not final:
            final = cfg.get("selling_price") or ""
            if final:
                logger.warning(f"[{code}] 名單沒填「最後定價」→ 暫用掛牌價 {final} 當 G 蝦皮售價，"
                               "毛利率會偏高，貼進 1-1 前請先補實際成交價")
        row[6] = str(final)
        row[9] = SPECIAL_ORDER_RATIO                         # J 特殊訂貨% = 100%
        row[10] = str(pd.get("shop_name") or "")             # K 廠商（抓得到才填）
        row[11] = _clean_url(item_id)                        # L 代表網址（正規化）
        products.append(row)

        tag = PREORDER_TAG if preorder else str(cfg.get("tag", "")).strip()
        sku_cat = ctx.sku_category(code)
        variants = p.get("variants", {})
        tier1 = variants.get("規格1_顏色") or []
        tier2 = variants.get("規格2_尺碼") or []
        size_map = _size_original_map(pd)

        pairs: list[dict] = []
        if tier2:
            for t1 in tier1:
                for t2 in tier2:
                    orig_size = size_map.get(str(t2["size"]).upper(), t2["size"])
                    pairs.append({
                        # key ＝ 直接取自同一份 variants 的兩個欄位 → 與 shopee_excel
                        # 用的 (c["src_1688"], s["size"]) 逐字相同，不靠順序對應
                        "key": (str(t1.get("src_1688", "")), str(t2.get("size", ""))),
                        "spec1": str(t1.get("src_1688", "")), "spec2": orig_size,
                        "display": f"{t1.get('color', '')}_{t2['size']}",
                        "price": _sku_price(pd, orig_size),
                    })
        else:
            for t1 in tier1:
                pairs.append({
                    "key": (str(t1.get("src_1688", "")), ""),
                    "spec1": str(t1.get("src_1688", "")), "spec2": "",
                    "display": str(t1.get("color", "")),
                    "price": str(price_cny) if price_cny > 0 else "",
                })

        # ── 配 SKU 品號（append-only：既有原文沿用舊碼、新原文才發新號）──
        # ⚠️ 三家品號體系完全不同，依賣場分派到各自的生碼器，**絕不共用一套規則**
        existing = collect_existing(ctx.sku_rows, code)
        spec_pairs = [(x["spec1"], x["spec2"]) for x in pairs]
        try:
            if str(shop).lower() == "nail":
                from scraper.sku_code_nail import allocate as nail_allocate
                # 商品序由「商品編號存不存在」決定（新編號開新序／既有編號接款式），
                # 不再有 attach_to——見 sku_code_nail 檔頭
                alloc = nail_allocate(code, spec_pairs, existing, ctx.nail)
            else:
                alloc = allocate(shop, code, spec_pairs, existing)
            codes = [a.sku_code for a in alloc.allocations]
        except UnsupportedShop as e:
            logger.warning(f"[{code}] {e} → 品號欄留空給人補")
            codes = [""] * len(pairs)
        except Exception as e:                    # 編號格式錯／未知品牌／歸屬查無，別讓整批掛掉
            logger.warning(f"[{code}] 品號生成失敗（{e}）→ 品號欄留空給人補")
            codes = [""] * len(pairs)

        for k, x in enumerate(pairs):
            skus.append({
                "owner_idx": idx, "item_id": item_id, "code": code, "key": x["key"],
                # H 安全存量：正式品用名單的「安全存量」，預購品統一 200。
                # ⚠️ 不填的話 `訂貨表 M 訂貨量試算 = H − K` 算不出缺口 →
                #    這些新 SKU 補貨時永遠不會被抓出來，而且不會有任何提示。
                "safety_stock": "" if preorder else str(cfg.get("stock_per_option") or ""),
                "sku_code": codes[k] if k < len(codes) else "",
                "category": sku_cat, "tag": tag, "preorder": preorder,
                "spec1": x["spec1"], "spec2": x["spec2"],
                "display": x["display"], "price": x["price"],
                "name": f"{code}_{short_name}_{x['display'].replace('_', ',')}",
            })
    return products, skus


def plan_blocks(shop: str, prepared: list[dict], sa_json: str | Path | None = None):
    """只讀 1-1、配好品號，**不寫任何東西**。回 (ctx, products, skus)。

    給兩個用途共用同一份配號結果：
    ① 上架 Excel 的 `O 商品選項貨號` —— 必須填 SKU 品號，獲利表是拿
       「蝦皮選項貨號 ＝ SKU 品號」去 join 進貨成本與銷量的（`model_sku_map`）。
       填 `HNV7_美規` 那種的話，這批商品的生意在獲利表裡會是黑的。
    ② 寫進 _待貼新品 分頁的 SKU 表 A 品號。
    **兩邊必須是同一次配號的結果**——各配一次雖然是純函式、結果相同，但只要
    中間有人動了 1-1，兩邊就會不一致，而且不會有任何錯誤訊息。
    """
    ctx = load_master_context(shop, sa_json)
    products, skus = build_blocks(shop, prepared, ctx)
    return ctx, products, skus


def option_sku_maps(skus: list[dict]) -> dict[int, dict[tuple[str, str], str]]:
    """plan_blocks 的 skus → {prepared 的 index: {(src_1688, size): 品號}}。"""
    out: dict[int, dict[tuple[str, str], str]] = {}
    for s in skus:
        if s.get("sku_code"):
            out.setdefault(s["owner_idx"], {})[s["key"]] = s["sku_code"]
    return out


def _open_master(shop: str, sa_json):
    import gspread
    from google.oauth2.service_account import Credentials

    from scraper.master_reader import SHOP_SHEETS, resolve_sa_json

    sa = resolve_sa_json(sa_json)
    creds = Credentials.from_service_account_file(
        str(sa), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sheet_id = SHOP_SHEETS[str(shop).lower()]
    return gc.open_by_key(sheet_id), sheet_id


def staging_has_leftover(shop: str, sa_json: str | Path | None = None) -> bool:
    """_待貼新品 是否還留著上一批資料（GUI 開跑前預檢，避免在背景執行緒跳對話框）。"""
    import gspread

    sh, _ = _open_master(shop, sa_json)
    try:
        ws = sh.worksheet(STAGING_TAB)
    except gspread.WorksheetNotFound:
        return False
    vals = ws.get_all_values()
    return any(cell.strip() for r in vals[2:] for cell in r)


def load_master_context(shop: str, sa_json: str | Path | None = None) -> MasterContext:
    """讀 1-1 正表（商品表 A:C、SKU表 A:M）建對照＋既有 SKU 列。"""
    sh, _ = _open_master(shop, sa_json)
    product_rows = sh.worksheet("商品表").get("A2:C5000")
    sku_rows = sh.worksheet("SKU表").get("A2:M8000")
    logger.info(f"[{shop}] 讀既有 1-1：商品表 {len(product_rows)} 列 / SKU表 {len(sku_rows)} 列")
    return MasterContext(product_rows, sku_rows, shop)


def write_staging(shop: str, prepared: list[dict], force: bool = False,
                  sa_json: str | Path | None = None) -> dict:
    """把 prepared 商品寫進該賣場 1-1 的 _待貼新品 分頁。

    分頁若還有上一批資料且 force=False → 丟 StagingNotEmpty（不默默清掉人還沒貼走的東西）。
    機器分頁採「刪掉重建」而非 clear()——gspread clear 只清值不清格式（#S163），
    重建才不會殘留上一批的黃底/格式。
    """
    import gspread

    if not prepared:
        return {"written": 0}
    sh, sheet_id = _open_master(shop, sa_json)

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

    # ⚠️ 先驗表頭契約再做事——不符就中止，寧可不寫也不要貼錯欄（貼錯不會報錯）
    verify_headers(sh, shop)

    ctx = load_master_context(shop, sa_json)
    products, skus = build_blocks(shop, prepared, ctx)
    n_pre = sum(1 for s in skus if s["preorder"])

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
    # ⚠️⚠️ **絕不可叫人整塊 A~U 貼**（2026-09-09）：商品表 F/H/I/R~U/V/W 與
    #    SKU表 K/O/P 是**錨在第 2 列的整欄陣列公式**，往下都是溢出格 —— 貼任何東西
    #    （含空白）進去就整欄 #REF!。用底色表達「哪些能貼」，不列一堆範圍
    #    （Edwin 2026-09-09：範圍太瑣碎記不住，看顏色就好）。
    rows1.append([f"■ 上區塊 → 貼到「商品表」最下方（欄序與商品表 A~U 完全一致）。"
                  f"**綠底欄＝直接貼；黃底欄＝不要貼**"
                  f"（黃底不是公式就是要人補，貼進去會把整欄陣列公式打成 #REF!）。"
                  f"資料在第 {b1_first}~{b1_last} 列"])
    rows1.append(PRODUCT_HEADERS + ["1688ID(勿貼)", "名單編號(參考,勿貼)"])
    for i, row in enumerate(products):
        meta = prepared[i].get("_meta", {})
        rows1.append(row + [str(meta.get("item_id", "")), str(meta.get("code", ""))])

    # ── 下區塊：SKU表 ──
    rows2: list[list[str]] = []
    rows2.append([f"■ 下區塊 → 貼到「SKU表」最下方（欄序與 SKU表 A~P 完全一致）。"
                  f"**綠底欄＝直接貼；黃底欄＝不要貼**。"
                  f"資料在第 {b2_first}~{b2_last} 列；貼完看 P 對應檢查該是 ✓"])

    rows2.append(SKU_HEADERS + ["1688ID(勿貼)", "規格顯示(勿貼)"])
    for s in skus:
        row = [""] * len(SKU_HEADERS)
        row[0] = s["sku_code"]              # A 品號（規則生成，append-only）
        row[1] = s["name"]                  # B 品名（編號_品名_規格，直接寫值）
        row[2] = s["category"]              # C 分類
        row[3] = s["tag"]                   # D 標籤（預購＝#PO_Sale）
        row[5] = s["price"]                 # F 進項成本（⚠️ 包裝品要換算單個）
        row[6] = "人民幣"                    # G 幣別
        # H 安全存量：預購統一 200；正式品用名單填的（Edwin 2026-09-09 要求帶入——
        # 他名單上已經填過一次，不該再手打第二次）
        row[7] = PREORDER_SAFETY_STOCK if s["preorder"] else s.get("safety_stock", "")
        row[11] = s["spec1"]                # L 規格一（1688 原文逐字）
        row[12] = s["spec2"]                # M 規格二（1688 原文逐字）
        rows2.append(row + [s["item_id"], s["display"]])

    ws.update(f"A{b1_note}", rows1, value_input_option="USER_ENTERED")
    ws.update(f"A{b2_note}", rows2, value_input_option="USER_ENTERED")

    # ── 格式（批次，避免 429）──
    def col_range(col0: int, first: int, last: int) -> str:
        return f"{a1(col0, first)}:{a1(col0, last)}"

    fmt: list[tuple[list[str], dict]] = []
    fmt.append(([f"A{b1_hdr}:{a1(len(PRODUCT_HEADERS) + 1, b1_hdr)}",
                 f"A{b2_hdr}:{a1(len(SKU_HEADERS) + 1, b2_hdr)}"],
                {"backgroundColor": BLUE_HDR, "textFormat": {"bold": True}}))

    # 黃底只標「機器沒填到」的格子，填到的不要打擾
    todo: list[str] = []
    for i, row in enumerate(products):
        for c in PRODUCT_TODO_COLS:
            if not str(row[c]).strip():
                todo.append(a1(c, b1_first + i))
    for j, s in enumerate(skus):
        if not str(s["price"]).strip():
            todo.append(a1(SKU_TODO_COLS[0], b2_first + j))
    if todo:
        fmt.append((todo, {"backgroundColor": YELLOW}))

    # J 特殊訂貨% 設成百分比，兩種貼法都不會跑掉（正表是 PERCENT 格式）
    if products:
        fmt.append(([col_range(9, b1_first, b1_last)],
                    {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}))
        fmt.append(([col_range(len(PRODUCT_HEADERS), b1_first, b1_last),
                     col_range(len(PRODUCT_HEADERS) + 1, b1_first, b1_last)],
                    {"textFormat": {"foregroundColor": GREY_TEXT}}))
    if skus:
        fmt.append(([col_range(len(SKU_HEADERS), b2_first, b2_last),
                     col_range(len(SKU_HEADERS) + 1, b2_first, b2_last)],
                    {"textFormat": {"foregroundColor": GREY_TEXT}}))
    for ranges, style in fmt:
        ws.format(ranges, style)

    kind = f"（預購 {n_pre} / 正式 {len(skus) - n_pre} SKU 列）"
    logger.info(f"[{shop}] {STAGING_TAB} 已寫入：{len(products)} 商品 / {len(skus)} SKU 列 {kind}")
    return {"written": len(products), "sku_rows": len(skus), "tab": STAGING_TAB,
            "sheet_id": sheet_id, "preorder_rows": n_pre}
