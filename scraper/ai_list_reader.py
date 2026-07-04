"""
讀「【Lady】AI 上架名單」Google Sheet（調整成給 AI 用的版本）→ 轉成 batch2 manifest。

跟人工採購表（`【女性周邊】2. 採購商品表`）的差別：AI 名單把 AI 需要的決策都補上了——
- J 欄「編號」(P-a1)         → code（變體命名 + 主貨號）
- K 欄「進貨網址」純文字 1688 URL → item_id（CSV 讀得到，不再是超連結）
- F 欄「分類」(長褲/上衣…)    → 蝦皮分類 ID（CATEGORY_MAP 對照）
- L 欄「款式」(三色長褲…)     → 挑色 hint（style_filter，配合抓到的色卡挑）
- M 欄「尺寸」(全尺寸/S-XL…)  → 挑尺碼
- T 欄「售價」(998)          → 蝦皮售價
- A 欄「訂貨需求」(預購/現貨)  → 預購標記

表結構：Row1 = 匯率；Row2-3 = 表頭（跨行）；Row4+ = 資料。
私有表 → CSV 由登入 Chrome 同源 fetch 落地成檔，本模組只負責解析檔案。
"""
import csv
import re
from pathlib import Path

from loguru import logger

# 蝦皮分類文字 → 分類 ID（在模板「較長備貨天數範圍」sheet 查 et_title_category_name/id）。
# 女裝常用先放這幾個，之後遇到新分類就補。查不到會 log 警告並留空（要求人工補）。
CATEGORY_MAP = {
    "長褲": "100358",   # 女生衣著/長褲（P-a1 實測過審用此 ID）
    "褲子": "100358",
    "闊腿褲": "100358",
    "寬褲": "100358",
    "T恤": "100352",    # 女生衣著/上衣/T恤
    "上衣": "100356",   # 女生衣著/上衣/其他上衣
    "短袖": "100352",
    "襯衫": "100353",   # 女生衣著/上衣/襯衫
}

# AI 名單欄位（0-indexed）— 依實際表頭固定
COL_DEMAND = 0    # A 訂貨需求
COL_NAME = 2      # C 商品名
COL_CATEGORY = 5  # F 分類
COL_SUPPLIER = 6  # G 廠商
COL_CODE = 9      # J 編號
COL_URL = 10      # K 進貨網址（1688）
COL_STYLE = 11    # L 款式（挑色 hint）
COL_SIZE = 12     # M 尺寸
COL_PRICE = 19    # T 售價

# Row1 = 匯率；Row2 = 表頭（雖然畫面上跨兩行，但因儲存格內含換行、csv.reader 視為一列）；
# 資料從第 3 列（index 2）起。
_HEADER_ROWS = 2


def _item_id(url: str) -> str | None:
    m = re.search(r"offer/(\d+)", url or "")
    return m.group(1) if m else None


def parse_ai_list_csv(csv_path: Path, stock_default: int = 10) -> list[dict]:
    """解析 AI 名單 CSV → batch2 manifest 的 products 清單。

    每筆：{item_id, code, price, stock, category, style_filter, sizes,
           demand, name, _category_text}
    - category 查不到 ID → 留空字串並 flag（跑 batch 時會擋，需人工補 CATEGORY_MAP）
    - colors 交給 style_filter（如「三色長褲」），在 batch 端配合抓到的色卡挑
    """
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))

    products = []
    for r in rows[_HEADER_ROWS:]:
        if len(r) <= COL_URL:
            continue
        url = r[COL_URL].strip() if len(r) > COL_URL else ""
        iid = _item_id(url)
        code = r[COL_CODE].strip() if len(r) > COL_CODE else ""
        name = r[COL_NAME].strip() if len(r) > COL_NAME else ""
        if not iid or not code:
            if name:
                logger.warning(f"跳過「{name}」：缺 1688 網址或編號（url={url[:40]}）")
            continue

        cat_text = r[COL_CATEGORY].strip() if len(r) > COL_CATEGORY else ""
        cat_id = CATEGORY_MAP.get(cat_text, "")
        if not cat_id:
            logger.warning(f"[{code}] 分類「{cat_text}」查無蝦皮 ID，請補 CATEGORY_MAP")

        price = 0
        if len(r) > COL_PRICE:
            try:
                price = int(float(r[COL_PRICE]))
            except (ValueError, TypeError):
                price = 0

        style = r[COL_STYLE].strip() if len(r) > COL_STYLE else ""
        size_text = r[COL_SIZE].strip() if len(r) > COL_SIZE else ""
        demand = r[COL_DEMAND].strip() if len(r) > COL_DEMAND else ""

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
        })
        logger.info(f"[{code}] {name} → item_id={iid} 分類={cat_text}({cat_id}) "
                    f"款式={style} 尺寸={size_text} 售價={price}")

    logger.info(f"AI 名單共解析 {len(products)} 筆")
    return products
