"""
讀「【Lady】AI 上架名單」Google Sheet（調整成給 AI 用的版本）→ 轉成 batch2 manifest。

跟人工採購表（`【女性周邊】2. 採購商品表`）的差別：AI 名單把 AI 需要的決策都補上了——
- 「編號」(P-a1)         → code（變體命名 + 主貨號）
- 「進貨網址」純文字 1688 URL → item_id（CSV 讀得到，不再是超連結）
- 「分類」(長褲/上衣…)    → 蝦皮分類 ID（CATEGORY_MAP 對照）
- 「款式」(三色長褲…)     → 挑色 hint（style_filter，配合抓到的色卡挑）
- 「尺寸」(全尺寸/S-XL…)  → 挑尺碼
- 「售價」(998)          → 蝦皮售價
- 「訂貨需求」(預購/現貨)  → 預購標記

⚠️ 欄位用「表頭名稱」動態對應，不寫死欄號——因為 Edwin 會在表裡插欄/搬欄
（實際踩過：插了一個「廠商」欄，害款式/尺寸/售價整排右移一格，寫死欄號全錯位）。
表結構：Row1 = 匯率；接著是表頭列（含「編號」「進貨網址」）；再往下是資料。
私有表 → CSV 由登入 Chrome 同源 gviz 下載落地成檔，本模組只負責解析檔案。
"""
import csv
import re
from pathlib import Path

from loguru import logger

# 蝦皮分類文字（「分類」欄）→ 分類 ID（在模板「較長備貨天數範圍」sheet 查）。
# Edwin 有填「分類」欄時優先用這張表；填的字要對得上 key。
CATEGORY_MAP = {
    "長褲": "100358",   # 女生衣著/長褲 / 緊身褲/長褲（P-a1 實測過審用此 ID）
    "褲子": "100358",
    "闊腿褲": "100358",
    "寬褲": "100358",
    "牛仔褲": "100103",  # 女生衣著/牛仔褲
    "短褲": "100360",   # 女生衣著/短褲/短褲
    "褲裙": "100361",   # 女生衣著/短褲/褲裙
    "裙裝": "100102",   # 女生衣著/裙裝
    "半身裙": "100102",
    "裙子": "100102",
    "T恤": "100352",    # 女生衣著/上衣/T恤
    "上衣": "100356",   # 女生衣著/上衣/其他上衣
    "短袖": "100352",
    "襯衫": "100353",   # 女生衣著/上衣/襯衫
}

# 「分類」欄空白時，從商品名（1688 原名，多為簡體）關鍵詞推斷分類 ID。
# 順序＝由具體到籠統（先攔「裙褲/牛仔」再到籠統「褲」），第一個命中就用。
# 只用真實存在的蝦皮 ID（讀 config/shopee_template.xlsx「較長備貨天數範圍」sheet 得來）。
_NAME_CATEGORY_RULES = [
    (["裙裤", "裙褲", "褲裙", "裤裙"], "100361"),                 # 褲裙
    (["牛仔"], "100103"),                                        # 牛仔褲
    (["半身裙", "花苞裙", "伞裙", "傘裙", "碎花裙", "a字裙", "连衣裙",
      "連衣裙", "长裙", "長裙", "短裙", "裙"], "100102"),          # 裙裝
    (["短裤", "短褲", "五分裤", "五分褲"], "100360"),             # 短褲
    (["阔腿", "闊腿", "西装裤", "西裝褲", "工装", "工裝", "运动裤",
      "運動褲", "山本", "弯刀", "彎刀", "喇叭", "直筒", "哈伦", "哈倫",
      "西裤", "西褲", "长裤", "長褲", "裤", "褲"], "100358"),      # 長褲
    (["t恤", "短袖", "上衣", "衬衫", "襯衫", "polo"], "100352"),   # 上衣/T恤
]


def _infer_category_from_name(name: str) -> str:
    """分類欄空白時，用商品名關鍵詞推斷蝦皮分類 ID；推不出回空字串。"""
    low = (name or "").lower()
    for keywords, cid in _NAME_CATEGORY_RULES:
        if any(k in low for k in keywords):
            return cid
    return ""

# 表頭名稱 → 內部欄位。每個欄位給幾個可能的表頭寫法（正規化後比對，去空白/換行）。
_HEADER_ALIASES = {
    "code": ["編號", "编号"],
    "url": ["進貨網址", "进货网址"],
    "name": ["商品or品牌名稱", "商品or品牌名称", "商品名稱", "商品名称", "品牌名稱"],
    "category": ["分類", "分类"],
    "style": ["款式"],
    "sizes": ["尺寸", "尺碼", "尺码"],
    "demand": ["訂貨需求", "订货需求"],
    "supplier": ["廠商", "厂商", "廠商名稱", "厂商名称"],
    "price": ["售價", "售价", "蝦皮售價", "蝦皮售价"],
}


def _norm(s: str) -> str:
    """表頭正規化：去所有空白/換行，方便比對（『商品 or 品牌名稱』→『商品or品牌名稱』）。"""
    return re.sub(r"\s+", "", (s or "")).strip()


def _item_id(url: str) -> str | None:
    m = re.search(r"offer/(\d+)", url or "")
    return m.group(1) if m else None


def _find_header_row(rows: list[list[str]]) -> int:
    """找表頭列：含「編號」且含「進貨網址」的那列（掃前 8 列）。找不到回退 index 1。"""
    for i, r in enumerate(rows[:8]):
        cells = {_norm(c) for c in r}
        if cells & {"編號", "编号"} and cells & {"進貨網址", "进货网址"}:
            return i
    return 1


def _build_colmap(header: list[str]) -> dict[str, int]:
    """表頭列 → {內部欄位: 欄 index}。同義字先到先得。"""
    normed = [_norm(c) for c in header]
    colmap: dict[str, int] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normed:
                colmap[field] = normed.index(alias)
                break
    return colmap


def _cell(row: list[str], idx: int | None) -> str:
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def _price_from_row(row: list[str], colmap: dict[str, int]) -> int:
    """取售價。優先用『售價』表頭欄；沒有表頭（Edwin 的表售價欄常無標題）就取
    尺寸欄右邊「最後一個純數字」——會跳過利潤率(65.14%)那種帶 % 的欄。"""
    if "price" in colmap:
        raw = _cell(row, colmap["price"]).replace(",", "")
        if re.fullmatch(r"\d+(\.\d+)?", raw):
            return int(float(raw))
    after = colmap.get("sizes", colmap.get("url", 0))
    for i in range(len(row) - 1, after, -1):
        v = row[i].strip().replace(",", "")
        if re.fullmatch(r"\d+(\.\d+)?", v):
            return int(float(v))
    return 0


def parse_ai_list_csv(csv_path: Path, stock_default: int = 10) -> list[dict]:
    """解析 AI 名單 CSV → batch2 manifest 的 products 清單（欄位靠表頭名稱對應）。

    每筆：{item_id, code, price, stock, category, style_filter, sizes,
           demand, name, _category_text}
    - category 查不到 ID → 留空字串並 flag（跑 batch 時會擋，需人工補 CATEGORY_MAP）
    - colors 交給 style_filter（如「三色長褲」），在 batch 端配合抓到的色卡挑
    """
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        logger.warning(f"{csv_path} 是空的")
        return []

    hdr_idx = _find_header_row(rows)
    colmap = _build_colmap(rows[hdr_idx])
    if "code" not in colmap or "url" not in colmap:
        logger.error(f"表頭找不到「編號」或「進貨網址」欄（表頭列 {hdr_idx}）：{rows[hdr_idx]}")
        return []
    logger.info(f"表頭在第 {hdr_idx} 列，欄位對應：{colmap}")

    products = []
    for r in rows[hdr_idx + 1:]:
        url = _cell(r, colmap.get("url"))
        iid = _item_id(url)
        code = _cell(r, colmap.get("code"))
        name = _cell(r, colmap.get("name"))
        if not iid or not code:
            if name or url:
                logger.warning(f"跳過「{name[:20]}」：缺 1688 網址或編號（url={url[:40]}）")
            continue

        cat_text = _cell(r, colmap.get("category"))
        cat_id = CATEGORY_MAP.get(cat_text, "")
        cat_src = "分類欄" if cat_id else ""
        if not cat_id:  # 分類欄空/對不上 → 從商品名推斷
            cat_id = _infer_category_from_name(name)
            if cat_id:
                cat_src = "商品名推斷"
        if not cat_id:
            logger.warning(f"[{code}] 分類「{cat_text}」查無 ID、商品名也推不出，請補分類或 CATEGORY_MAP")

        price = _price_from_row(r, colmap)
        style = _cell(r, colmap.get("style"))
        size_text = _cell(r, colmap.get("sizes"))
        demand = _cell(r, colmap.get("demand"))

        products.append({
            "item_id": iid,
            "code": code,
            "price": price,
            "stock": stock_default,
            "category": cat_id,
            "style_filter": style,       # 「三色長褲」等 → batch 端配合色卡挑
            "sizes": "all" if ("全" in size_text or not size_text) else size_text,
            "demand": demand,
            # 預購品填較長備貨天數（AP 欄）；現貨留空
            "pre_order_days": 10 if "預購" in demand else None,
            "name": name,
            "reuse_content": False,
            "_category_text": cat_text,
            "_category_source": cat_src,   # 分類欄 / 商品名推斷 / 空
        })
        logger.info(f"[{code}] {name[:16]} → item_id={iid} "
                    f"分類={cat_id or '(無)'}[{cat_src or '未定'}] "
                    f"款式={style[:10]} 尺寸={size_text} 售價={price}")

    logger.info(f"AI 名單共解析 {len(products)} 筆")
    return products
