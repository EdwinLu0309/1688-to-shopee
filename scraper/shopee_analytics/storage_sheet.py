"""Google Sheet 落地（真相來源 — Edwin 打得開、可親自核對）。

分頁規劃（承 #S097：一年一檔可再拆，量大按月分頁、原始分頁純值零公式）：
- `商品日報_YYYYMM`：逐商品 × 每日（Lady 店約 437 列/天 → ~1.3 萬列/月）
- `規格日報_YYYYMM`：逐規格 × 每日（994 列/天 → ~3 萬列/月）。「規格名稱」
  就是 Edwin 成本/毛利對帳用的 key（對成本表算當時匯率+運費 → 月獲利表）
- `大盤日報_YYYY`：一天一列（funnel + 來源拆分 + key metrics）

表頭一律中文（`_CN`/`_cn()` 對照；英文 key 只留在 code/SQLite/raw）。

憑證沿用 inventory-sync 慣例：環境變數 GOOGLE_SERVICE_ACCOUNT_JSON
（JSON 字串或檔案路徑皆可）。sheet_id 由 config/shopee_analytics.json 指定。

冪等：同一天重跑會先刪掉該 shop+日期舊列再 append（安全重抓）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger

from .collector import (
    AD_META_FIELDS,
    AD_REPORT_FIELDS,
    AD_TOTAL_FIELDS,
    DayData,
    FUNNEL_FIELDS,
    MODEL_FIELDS,
    PRODUCT_FIELDS,
    SOURCE_FIELDS,
)

_AD_COLS = AD_META_FIELDS + AD_REPORT_FIELDS

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_SHOP_DAILY_COLS = (
    FUNNEL_FIELDS
    + [f"src_{f}" for f in SOURCE_FIELDS]
    + [f"src_{f}_ratio" for f in SOURCE_FIELDS]
    + ["shop_pv"]
    + AD_TOTAL_FIELDS
)

# ── 中文表頭（Edwin 看得懂＝真相來源的基本要求；英文 key 只留在 code/SQLite）──
_CN = {
    "id": "商品ID", "name": "商品名稱", "status": "狀態",
    "product_card_impressions": "商品卡曝光數", "product_card_clicks": "商品卡點擊數",
    "ctr": "點擊率", "search_clicks": "搜尋點擊數",
    "uv": "商品訪客數", "pv": "商品瀏覽數", "bounce_rate": "跳出率", "likes": "按讚數",
    "add_to_cart_units": "加購件數", "add_to_cart_buyers": "加購人數",
    "placed_sales": "下單金額", "placed_units": "下單件數",
    "placed_buyers": "下單買家數", "placed_orders": "下單訂單數",
    "paid_sales": "付款金額", "paid_units": "付款件數",
    "paid_buyers": "付款買家數", "paid_orders": "付款訂單數",
    "confirmed_sales": "確認銷售額", "confirmed_units": "確認銷售件數",
    "confirmed_buyers": "確認買家數", "confirmed_orders": "確認訂單數",
    "placed_order_conversion_rate": "下單轉換率",
    "confirmed_order_conversion_rate": "確認轉換率",
    "uv_to_add_to_cart_rate": "訪客加購率", "uv_to_placed_buyers_rate": "訪客下單率",
    # 大盤 funnel
    "shop_uv": "商店訪客數", "hybrid_uv": "不重複訪客數",
    "confirmed_sales_per_buyer": "客單價(確認)", "shop_pv": "商店瀏覽數",
    # 廣告
    "campaign_id": "活動ID", "title": "活動名稱", "type": "活動類型", "state": "狀態",
    "daily_budget": "日預算", "total_budget": "總預算",
    "cost": "花費", "impression": "曝光數", "click": "點擊數", "ctr": "點擊率",
    "cpc": "每次點擊成本", "cpm": "每千次曝光成本",
    "atc": "加購數", "atc_rate": "加購率", "checkout": "結帳數", "cr": "轉換率",
    "broad_order": "廣義訂單數", "broad_gmv": "廣義成交額", "broad_roi": "廣義ROAS",
    "broad_cir": "廣義投產比", "direct_order": "直接訂單數", "direct_gmv": "直接成交額",
    "direct_roi": "直接ROAS", "direct_cir": "直接投產比",
    "page_views": "頁面瀏覽", "unique_visitors": "不重複訪客", "avg_rank": "平均排名",
    # 大盤的廣告合計（明細加總；含自動選品全賣場推廣）
    "ad_cost": "廣告總花費", "ad_gmv": "廣告成交額", "ad_roi": "廣告ROAS",
}
_SRC_CN = {
    "total_sales": "總銷售額", "product_card": "商品卡片", "live": "直播",
    "video": "影片", "affiliate": "聯盟行銷", "paid_ads": "廣告",
}


def _cn(field: str) -> str:
    if field.startswith("src_"):
        key = field[4:]
        if key.endswith("_ratio"):
            return f"來源佔比｜{_SRC_CN.get(key[:-6], key)}"
        return f"來源銷售額｜{_SRC_CN.get(key, key)}"
    return _CN.get(field, field)


PRODUCT_HEADER = ["日期", "賣場"] + [_cn(f) for f in PRODUCT_FIELDS]
MODEL_HEADER = (
    ["日期", "賣場", "商品ID", "商品名稱", "規格ID", "規格名稱", "狀態"]
    + [_cn(f) for f in MODEL_FIELDS if f not in ("id", "name", "status")]
)
SHOP_HEADER = ["日期", "賣場"] + [_cn(f) for f in _SHOP_DAILY_COLS]
AD_HEADER = ["日期", "賣場"] + [_cn(f) for f in _AD_COLS]


def _get_client():
    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        # 沒設環境變數就退回專案既有 SA 路徑（同 ordering 套件，inventory-sync SA）
        from config import settings

        raw = settings.ORDER_SHEET_SA_JSON
    if raw.startswith("{"):
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(raw, scopes=SCOPES)
    return gspread.authorize(creds)


def _ensure_ws(sh, title: str, header: list[str], rows: int = 2000):
    try:
        ws = sh.worksheet(title)
    except Exception:  # WorksheetNotFound
        ws = sh.add_worksheet(title=title, rows=rows, cols=len(header) + 2)
        ws.append_row(header, value_input_option="RAW")
        logger.info(f"建立分頁 {title}")
        return ws
    # 表頭跟預期不同（如舊版英文表頭）→ 就地換掉第 1 列
    if ws.row_values(1) != header:
        ws.update(values=[header], range_name="A1", raw=True)
        logger.info(f"分頁 {title} 表頭已更新（{len(header)} 欄）")
    return ws


def _delete_day_rows(sh, ws, dt: str, shop: str) -> int:
    """冪等：刪掉同日期+賣場的舊列。

    ⚠️ 不能逐列 delete_rows（423 列＝423 次寫入 API → 必炸 429 quota）；
    把要刪的列併成連續區間，一次 batch_update 刪完。
    """
    values = ws.get_values("A:B")
    to_delete = [
        i for i, row in enumerate(values)  # 0-based index
        if len(row) >= 2 and row[0] == dt and row[1] == shop
    ]
    if not to_delete:
        return 0
    # 併連續區間（如 [5,6,7,20,21] → [(5,8),(20,22)]，end exclusive）
    ranges: list[tuple[int, int]] = []
    start = prev = to_delete[0]
    for idx in to_delete[1:]:
        if idx == prev + 1:
            prev = idx
        else:
            ranges.append((start, prev + 1))
            start = prev = idx
    ranges.append((start, prev + 1))
    # 由下往上刪避免位移；全部塞進一次 batch_update
    requests = [
        {"deleteDimension": {"range": {
            "sheetId": ws.id, "dimension": "ROWS",
            "startIndex": s, "endIndex": e,
        }}}
        for s, e in sorted(ranges, reverse=True)
    ]
    sh.batch_update({"requests": requests})
    return len(to_delete)


def save(data: DayData, sheet_id: str) -> None:
    gc = _get_client()
    sh = gc.open_by_key(sheet_id)
    dt = data.dt.isoformat()

    # 商品日報（按月分頁）
    ws = _ensure_ws(sh, f"商品日報_{data.dt:%Y%m}", PRODUCT_HEADER, rows=15000)
    deleted = _delete_day_rows(sh, ws, dt, data.shop)
    if deleted:
        logger.info(f"商品日報 冪等清除舊列 {deleted} 筆")
    rows = [[dt, data.shop] + [r.get(f, "") for f in PRODUCT_FIELDS] for r in data.products]
    if rows:
        ws.append_rows(rows, value_input_option="RAW")

    # 規格日報（按月分頁；成本/毛利對帳的主角——「規格名稱」對成本表）
    wsm = _ensure_ws(sh, f"規格日報_{data.dt:%Y%m}", MODEL_HEADER, rows=35000)
    deleted = _delete_day_rows(sh, wsm, dt, data.shop)
    if deleted:
        logger.info(f"規格日報 冪等清除舊列 {deleted} 筆")
    pname = {p.get("id"): p.get("name", "") for p in data.products}
    metric_fields = [f for f in MODEL_FIELDS if f not in ("id", "name", "status")]
    mrows = [
        [dt, data.shop, m.get("product_id", ""), pname.get(m.get("product_id"), ""),
         m.get("id", ""), m.get("name", ""), m.get("status", "")]
        + [m.get(f, "") for f in metric_fields]
        for m in data.models
    ]
    if mrows:
        wsm.append_rows(mrows, value_input_option="RAW")

    # 大盤日報（按年分頁）
    ws2 = _ensure_ws(sh, f"大盤日報_{data.dt:%Y}", SHOP_HEADER, rows=400)
    deleted = _delete_day_rows(sh, ws2, dt, data.shop)
    if deleted:
        logger.info(f"大盤日報 冪等清除舊列 {deleted} 筆")
    ws2.append_rows(
        [[dt, data.shop] + [data.shop_daily.get(c, "") for c in _SHOP_DAILY_COLS]],
        value_input_option="RAW",
    )

    # 廣告日報（按月分頁；一活動一列，只含當天有跑的）
    wsa = _ensure_ws(sh, f"廣告日報_{data.dt:%Y%m}", AD_HEADER, rows=10000)
    deleted = _delete_day_rows(sh, wsa, dt, data.shop)
    if deleted:
        logger.info(f"廣告日報 冪等清除舊列 {deleted} 筆")
    arows = [[dt, data.shop] + [a.get(c, "") for c in _AD_COLS] for a in data.ads]
    if arows:
        wsa.append_rows(arows, value_input_option="RAW")

    logger.info(
        f"Google Sheet 已寫入：商品 {len(rows)} 列 + 規格 {len(mrows)} 列 + "
        f"大盤 1 列 + 廣告 {len(arows)} 列（{dt} {data.shop}）"
    )
