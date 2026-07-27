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

from .pending_scraper import (
    ARRIVAL_HEADERS, DB_HEADERS, OrderRecord, merge_arrival_grid,
    to_arrival_grid, to_db_grid,
)

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
                  updated_time: str | None = None, arrival: bool = False) -> dict:
        """用抓到的訂單覆蓋 1688_DB 資料區。回傳 {orders, rows, updated_time}。

        版面：第1列「來源檔案名稱：」、第2列「最後更新時間：」、第3列表頭、第4列起資料。
        arrival=True → 到貨版 50 欄格式（含運單號在 AF）；否則金額版 26 欄。

        ⚠️ 到貨版（arrival）是「合併累加」不是整張覆蓋：先讀舊 1688_DB，新抓的訂單為主、
        缺運單號時回填舊值，舊有但這次沒抓到的訂單（已離開待收貨）整組保留——否則訂單一離開
        待收貨、運單號就從 DB 消失，到貨分頁 XLOOKUP 全部對不到。金額版仍是純覆蓋（反映現況）。
        """
        updated_time = updated_time or _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        headers = ARRIVAL_HEADERS if arrival else DB_HEADERS
        grid = to_arrival_grid(records) if arrival else to_db_grid(records)

        ws = self._sh.worksheet(self.tab)

        if arrival:
            # 讀舊資料區（前 3 列為來源/更新時間/表頭）合併，保住既有運單號
            try:
                existing = ws.get_all_values()
                old_grid = existing[3:] if len(existing) > 3 else []
            except Exception as e:
                logger.warning(f"讀舊 1688_DB 失敗（改為純覆蓋，可能遺失舊運單號）：{e}")
                old_grid = []
            grid = merge_arrival_grid(old_grid, grid)

        top1 = ["來源檔案名稱：", source_name]
        top2 = ["最後更新時間：", updated_time]
        values = [top1, top2, list(headers)] + grid

        ws.clear()
        ws.update(values, value_input_option="USER_ENTERED")
        verb = "合併" if arrival else "覆蓋"
        logger.info(f"1688_DB {verb}完成：新抓 {len(records)} 訂單 / 寫入 {len(grid)} 列（{updated_time}）")
        return {"orders": len(records), "rows": len(grid), "updated_time": updated_time}
