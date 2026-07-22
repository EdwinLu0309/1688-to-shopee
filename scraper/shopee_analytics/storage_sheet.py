"""Google Sheet 落地（真相來源 — Edwin 打得開、可親自核對）。

分頁規劃（承 #S097：一年一檔可再拆，量大按月分頁、原始分頁純值零公式）：
- `商品日報_YYYYMM`：逐商品 × 每日（Lady 店約 437 列/天 → ~1.3 萬列/月）
- `大盤日報_YYYY`：一天一列（funnel + 來源拆分 + key metrics）

憑證沿用 inventory-sync 慣例：環境變數 GOOGLE_SERVICE_ACCOUNT_JSON
（JSON 字串或檔案路徑皆可）。sheet_id 由 config/shopee_analytics.json 指定。

冪等：同一天重跑會先刪掉該 shop+日期舊列再 append（安全重抓）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger

from .collector import DayData, FUNNEL_FIELDS, PRODUCT_FIELDS, SOURCE_FIELDS

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_SHOP_DAILY_COLS = (
    FUNNEL_FIELDS
    + [f"src_{f}" for f in SOURCE_FIELDS]
    + [f"src_{f}_ratio" for f in SOURCE_FIELDS]
    + ["shop_pv"]
)

PRODUCT_HEADER = ["日期", "賣場"] + PRODUCT_FIELDS
SHOP_HEADER = ["日期", "賣場"] + _SHOP_DAILY_COLS


def _get_client():
    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"].strip()
    if raw.startswith("{"):
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(raw, scopes=SCOPES)
    return gspread.authorize(creds)


def _ensure_ws(sh, title: str, header: list[str], rows: int = 2000):
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=rows, cols=len(header) + 2)
        ws.append_row(header, value_input_option="RAW")
        logger.info(f"建立分頁 {title}")
    return ws


def _delete_day_rows(ws, dt: str, shop: str) -> int:
    """冪等：刪掉同日期+賣場的舊列（由下往上刪避免位移）。"""
    values = ws.get_values("A:B")
    to_delete = [
        i + 1 for i, row in enumerate(values)
        if len(row) >= 2 and row[0] == dt and row[1] == shop
    ]
    for idx in reversed(to_delete):
        ws.delete_rows(idx)
    return len(to_delete)


def save(data: DayData, sheet_id: str) -> None:
    gc = _get_client()
    sh = gc.open_by_key(sheet_id)
    dt = data.dt.isoformat()

    # 商品日報（按月分頁）
    ws = _ensure_ws(sh, f"商品日報_{data.dt:%Y%m}", PRODUCT_HEADER, rows=15000)
    deleted = _delete_day_rows(ws, dt, data.shop)
    if deleted:
        logger.info(f"商品日報 冪等清除舊列 {deleted} 筆")
    rows = [[dt, data.shop] + [r.get(f, "") for f in PRODUCT_FIELDS] for r in data.products]
    if rows:
        ws.append_rows(rows, value_input_option="RAW")

    # 大盤日報（按年分頁）
    ws2 = _ensure_ws(sh, f"大盤日報_{data.dt:%Y}", SHOP_HEADER, rows=400)
    deleted = _delete_day_rows(ws2, dt, data.shop)
    if deleted:
        logger.info(f"大盤日報 冪等清除舊列 {deleted} 筆")
    ws2.append_rows(
        [[dt, data.shop] + [data.shop_daily.get(c, "") for c in _SHOP_DAILY_COLS]],
        value_input_option="RAW",
    )
    logger.info(f"Google Sheet 已寫入：商品 {len(rows)} 列 + 大盤 1 列（{dt} {data.shop}）")
