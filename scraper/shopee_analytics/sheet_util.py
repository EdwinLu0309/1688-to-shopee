"""分析層各分頁共用的 gspread 小工具（開表 / 確保分頁 / 覆蓋寫）。

憑證與 storage_sheet 同一套（`_get_client`：env GOOGLE_SERVICE_ACCOUNT_JSON
或退回 settings.ORDER_SHEET_SA_JSON＝inventory-sync SA）。
"""

from __future__ import annotations

from loguru import logger

from .storage_sheet import _get_client


def open_sheet(sheet_id: str):
    return _get_client().open_by_key(sheet_id)


def ensure_ws(sh, title: str, rows: int = 200, cols: int = 26):
    """取分頁，沒有就建。回 worksheet。"""
    try:
        return sh.worksheet(title)
    except Exception:  # WorksheetNotFound
        ws = sh.add_worksheet(title=title, rows=rows, cols=cols)
        logger.info(f"建立分頁 {title}")
        return ws


def overwrite(ws, values: list[list], resize_cols: int | None = None) -> None:
    """整片覆蓋一個分頁：先清空再從 A1 寫入 2D values（RAW）。"""
    ws.clear()
    if not values:
        return
    ncols = resize_cols or max(len(r) for r in values)
    # 補齊每列長度（gspread update 要求等長；短列補空字串）
    norm = [row + [""] * (ncols - len(row)) for row in values]
    ws.update(values=norm, range_name="A1", raw=True)
