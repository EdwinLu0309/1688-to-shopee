"""金流核對表的 1688_DB 分頁寫入（覆蓋式，比照 Edwin 手動「匯出→貼進 DB」）。

用 inventory-sync 的 SA（已確認對此表有編輯權）。刷新＝重抓 1688 待付款訂單 → 覆蓋
1688_DB 資料區（第4列起）+ 更新頂端「最後更新時間」；各日期核對分頁靠「卖家公司名」
VLOOKUP 進來，故只動 1688_DB、不碰任何核對分頁。
"""

from __future__ import annotations

import datetime as _dt

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

from config import settings

from .pending_scraper import DB_HEADERS, OrderRecord, to_db_grid

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class ReconcileDB:
    """封裝金流核對表 1688_DB 分頁的覆蓋寫入。"""

    def __init__(self, sheet_id: str | None = None, tab: str | None = None,
                 sa_json: str | None = None):
        self.sheet_id = sheet_id or settings.RECONCILE_SHEET_ID
        self.tab = tab or settings.RECONCILE_DB_TAB
        self.sa_json = sa_json or settings.ORDER_SHEET_SA_JSON
        creds = Credentials.from_service_account_file(self.sa_json, scopes=_SCOPES)
        self._gc = gspread.authorize(creds)
        self._sh = self._gc.open_by_key(self.sheet_id)
        logger.debug(f"已開啟金流核對表：{self._sh.title}")

    def overwrite(self, records: list[OrderRecord], source_name: str = "1688 刷新",
                  updated_time: str | None = None) -> dict:
        """用抓到的訂單覆蓋 1688_DB 資料區。回傳 {orders, rows, updated_time}。

        版面：第1列「來源檔案名稱：」、第2列「最後更新時間：」、第3列表頭、第4列起資料。
        """
        updated_time = updated_time or _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        grid = to_db_grid(records)

        top1 = ["來源檔案名稱：", source_name]
        top2 = ["最後更新時間：", updated_time]
        values = [top1, top2, list(DB_HEADERS)] + grid

        ws = self._sh.worksheet(self.tab)
        ws.clear()
        ws.update(values, value_input_option="USER_ENTERED")
        logger.info(f"1688_DB 覆蓋完成：{len(records)} 訂單 / {len(grid)} 列（{updated_time}）")
        return {"orders": len(records), "rows": len(grid), "updated_time": updated_time}
