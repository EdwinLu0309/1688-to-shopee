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
MASTER_TAB_GID = 1584079803  # 「商品表」分頁（商品編號/代表網址/廠商… 權威來源）
# 2026-07-29：Edwin 把「要產/資產包狀態」兩欄從「商品表」搬到「蝦皮處理狀態」分頁。
# 一鍵同步改成：商品資訊讀「商品表」、勾選/完成狀態讀寫「蝦皮處理狀態」（以商品編號 join）。
STATUS_TAB_TITLE = "蝦皮處理狀態"

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
    "asset_status": ["資產包狀態", "资产包状态"],
    "want": ["要產", "要产"],
}

_TRUE = {"TRUE", "True", "true", "✓", "V", "v", "是", "1", "yes", "Y"}


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


def _col_letter(idx0: int) -> str:
    """0-based 欄 index → A1 字母（0→A、17→R、18→S…）。"""
    s = ""
    n = idx0
    while True:
        s = chr(ord("A") + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def open_for_sync(sa_json: str | Path | None = None):
    """開主表供「一鍵同步」用。回 (ws_status, status_colmap, records)。

    - 商品資訊（item_id/code/name/supplier/url）讀自「商品表」分頁。
    - want(要產勾選)/asset_done(資產包狀態✓) 讀自「蝦皮處理狀態」分頁，以商品編號 join；
      回寫（write_status）也寫「蝦皮處理狀態」→ 故回傳的 ws 是該分頁、colmap 是該分頁的。
    - _row = 該商品在「蝦皮處理狀態」的 1-based 列號（供回寫）。
    - 只收「在蝦皮處理狀態有對應列」且「商品表有代表網址」的商品；不在蝦皮處理狀態的
      （未上架子集）目前無法用勾選驅動 → 略過（見 CLAUDE.md 覆蓋範圍註記）。
    """
    import gspread

    sa = resolve_sa_json(sa_json)
    if not sa:
        raise FileNotFoundError("找不到 SA 憑證（參數/settings/OneDrive 都沒有）")
    gc = gspread.service_account(filename=str(sa))
    sh = gc.open_by_key(MASTER_SHEET_ID)

    ws_prod = sh.get_worksheet_by_id(MASTER_TAB_GID)
    prod_rows = ws_prod.get_all_values()
    prod_colmap = _build_colmap(prod_rows[0]) if prod_rows else {}

    ws_status = sh.worksheet(STATUS_TAB_TITLE)
    status_rows = ws_status.get_all_values()
    status_colmap = _build_colmap(status_rows[0]) if status_rows else {}
    if "want" not in status_colmap and "asset_status" not in status_colmap:
        logger.error(
            f"「{STATUS_TAB_TITLE}」找不到「要產」或「資產包狀態」欄；表頭＝{status_rows[0] if status_rows else '(空)'}"
        )

    # 蝦皮處理狀態：商品編號 → {want, asset_done, _row}（同編號取第一筆）
    status_by_code: dict[str, dict] = {}
    for i, r in enumerate(status_rows[1:], start=2):  # 1-based（含表頭第 1 列）
        code = _cell(r, status_colmap.get("code"))
        if not code or code in status_by_code:
            continue
        status_by_code[code] = {
            "want": _cell(r, status_colmap.get("want")) in _TRUE,
            "asset_done": bool(_cell(r, status_colmap.get("asset_status"))),
            "_row": i,
        }

    records = []
    for r in prod_rows[1:]:
        url = _cell(r, prod_colmap.get("url"))
        iid = _item_id(url)
        code = _cell(r, prod_colmap.get("code"))
        if not iid or not code:
            continue
        st = status_by_code.get(code)
        if not st:  # 商品表有、但蝦皮處理狀態沒這編號 → 無法勾選驅動，略過
            continue
        records.append({
            "item_id": iid, "code": code,
            "name": _cell(r, prod_colmap.get("name")),
            "supplier": _cell(r, prod_colmap.get("supplier")),
            "url": url, "_row": st["_row"],
            "want": st["want"], "asset_done": st["asset_done"],
        })
    logger.info(
        f"一鍵同步讀到 {len(records)} 個商品（蝦皮處理狀態 {len(status_by_code)} 個編號有狀態列）"
    )
    return ws_status, status_colmap, records


def write_status(ws, colmap: dict, row: int, done: bool = True, clear_want: bool = True) -> None:
    """回寫某列（蝦皮處理狀態分頁）：資產包狀態＝✓、清掉要產勾選。"""
    reqs = []
    if "asset_status" in colmap:
        reqs.append((f"{_col_letter(colmap['asset_status'])}{row}", "✓" if done else ""))
    if clear_want and "want" in colmap:
        reqs.append((f"{_col_letter(colmap['want'])}{row}", False))
    for a1, val in reqs:
        ws.update(range_name=a1, values=[[val]])
