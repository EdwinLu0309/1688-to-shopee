"""
讀「【Nail】1-1. 商品主表 → 商品表」分頁 → 商品資產包的權威驅動來源。

主表是全系統（訂貨/庫存/資產包）共用的商品編號來源。欄位（靠表頭名稱對應，不寫死欄號）：
  商品編號 | 分類 | 子分類 | 品名 | 成本 | 台幣成本 | 蝦皮售價 | … | 廠商 | 代表網址 | 狀態 | 標籤 …

用途（product_card）：
- 資產包資料夾名 = 商品編號（AAS1…，跨系統一致，取代 1688 數字 item_id）
- 商品卡「廠商」優先用主表（抓取常抓不到店名）
- 代表網址 → 1688 item_id（抓取來源 + 對應 output/{item_id}.json）
- 分類/子分類/售價等我方決策欄「不進商品卡」，但回傳給呼叫端做判斷/落夾

SA 憑證沿用 inventory-sync（需被分享為此表讀者）。
"""
import re
from pathlib import Path

from loguru import logger

MASTER_SHEET_ID = "1eL58RfE_a5AQpSE4qGcLi0AsMKdDO_NLAsfB76NmtRc"
MASTER_TAB_GID = 1584079803  # 「商品表」分頁

# 表頭名稱 → 內部欄位（正規化後比對；同義字先到先得）。
_HEADER_ALIASES = {
    "code": ["商品編號", "商品编号", "編號", "编号"],
    "category": ["分類", "分类"],
    "subcategory": ["子分類", "子分类"],
    "name": ["品名", "商品名稱", "商品名称"],
    "supplier": ["廠商", "厂商", "廠商名稱"],
    "url": ["代表網址", "代表网址", "1688網址", "1688网址", "進貨網址"],
    "price": ["蝦皮售價", "蝦皮售价", "售價", "售价"],
    "status": ["狀態", "状态"],
    "tag": ["標籤", "标签"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).strip()


def _item_id(url: str) -> str | None:
    m = re.search(r"offer/(\d+)", url or "")
    return m.group(1) if m else None


def resolve_sa_json(sa_json: str | Path | None = None) -> Path | None:
    """找 SA 憑證：參數 → settings.ORDER_SHEET_SA_JSON → 這台 OneDrive/文件 fallback。"""
    cands: list[Path] = []
    if sa_json:
        cands.append(Path(sa_json))
    try:
        from config.settings import ORDER_SHEET_SA_JSON
        cands.append(Path(ORDER_SHEET_SA_JSON))
    except Exception:
        pass
    cands.append(Path.home() / "OneDrive" / "文件" / "inventory-sync-493112-6047c28ad2b1.json")
    for p in cands:
        if p and p.exists():
            return p
    return None


def _build_colmap(header: list[str]) -> dict[str, int]:
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


def read_master(
    sheet_id: str = MASTER_SHEET_ID,
    gid: int = MASTER_TAB_GID,
    sa_json: str | Path | None = None,
) -> dict[str, dict]:
    """讀主表 → {item_id: {code, category, subcategory, name, supplier, price, url, status, tag}}。

    只收「有代表網址（能解析出 item_id）且有商品編號」的列。item_id 當 key（對 output/{item_id}.json）。
    """
    import gspread

    sa = resolve_sa_json(sa_json)
    if not sa:
        raise FileNotFoundError("找不到 SA 憑證（參數/settings/OneDrive 都沒有）")

    gc = gspread.service_account(filename=str(sa))
    ws = gc.open_by_key(sheet_id).get_worksheet_by_id(gid)
    rows = ws.get_all_values()
    if not rows:
        logger.warning("主表是空的")
        return {}

    colmap = _build_colmap(rows[0])
    if "code" not in colmap or "url" not in colmap:
        logger.error(f"主表表頭找不到「商品編號」或「代表網址」：{rows[0]}")
        return {}

    out: dict[str, dict] = {}
    for r in rows[1:]:
        code = _cell(r, colmap.get("code"))
        url = _cell(r, colmap.get("url"))
        iid = _item_id(url)
        if not code or not iid:
            continue
        out[iid] = {
            "code": code,
            "category": _cell(r, colmap.get("category")),
            "subcategory": _cell(r, colmap.get("subcategory")),
            "name": _cell(r, colmap.get("name")),
            "supplier": _cell(r, colmap.get("supplier")),
            "price": _cell(r, colmap.get("price")),
            "url": url,
            "status": _cell(r, colmap.get("status")),
            "tag": _cell(r, colmap.get("tag")),
        }
    logger.info(f"主表讀到 {len(out)} 個有代表網址的商品")
    return out
