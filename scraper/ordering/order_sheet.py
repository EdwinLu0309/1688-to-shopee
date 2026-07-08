"""訂貨系統的 Google Sheet 客戶端（三分頁讀寫）。

用 inventory-sync 的 SA 憑證（需被分享為此表編輯者）。

分頁欄位（0-index，實測 2026-07）：
  1_訂貨主檔  : 0 貨號 | 1 編號 | 2 簡稱 | 3 1688網址 | 4 規格一 | 5 規格二 | 6 進貨單價¥
  2_每日訂購彙總: 0 日期 | 1 貨號 | 2 編號 | 3 簡稱 | 4 規格一 | 5 規格二 | 6 總數量 | 7 進貨¥ | 8 成本小計 | 9 下單狀態 | 10 下單時間
  3_訂單明細  : 0 日期 | 1 訂單編號 | 2 買家帳號 | 3 貨號 | 4 編號 | 5 數量 | 6 出貨狀態 | 7 備註
"""

from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

from config import settings

from .models import MasterEntry, SummaryRow

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 明細分頁欄序（寫入用）
DETAIL_HEADERS = ["日期", "訂單編號", "買家帳號", "商品選項貨號", "編號", "數量", "出貨狀態", "備註"]
# 彙總分頁欄序
SUMMARY_HEADERS = [
    "日期", "商品選項貨號", "編號", "商品簡稱", "規格一(1688原色)",
    "規格二(1688尺碼)", "總數量", "進貨¥", "成本小計", "下單狀態", "下單時間",
]

DEFAULT_SHIP_STATUS = "待出貨"


class OrderSheet:
    """封裝訂貨表三分頁的讀寫。"""

    def __init__(
        self,
        sheet_id: str | None = None,
        sa_json: str | None = None,
    ):
        self.sheet_id = sheet_id or settings.ORDER_SHEET_ID
        self.sa_json = sa_json or settings.ORDER_SHEET_SA_JSON
        creds = Credentials.from_service_account_file(self.sa_json, scopes=_SCOPES)
        self._gc = gspread.authorize(creds)
        self._sh = self._gc.open_by_key(self.sheet_id)
        logger.debug(f"已開啟訂貨表：{self._sh.title}")

    # ── 分頁1：訂貨主檔（讀）──────────────────────────────
    def load_master(self) -> dict[str, MasterEntry]:
        """讀訂貨主檔 → {商品選項貨號: MasterEntry}。空貨號列略過。"""
        ws = self._sh.worksheet(settings.ORDER_MASTER_TAB)
        rows = ws.get_all_values()
        master: dict[str, MasterEntry] = {}
        dup = 0
        for row in rows[1:]:  # 跳表頭
            sku = _get(row, 0)
            if not sku:
                continue
            if sku in master:
                dup += 1
            master[sku] = MasterEntry(
                sku_code=sku,
                code=_get(row, 1),
                short_name=_get(row, 2),
                url_1688=_get(row, 3),
                spec1=_get(row, 4),
                spec2=_get(row, 5),
                cost_cny=_parse_num(_get(row, 6)),
            )
        if dup:
            logger.warning(f"訂貨主檔有 {dup} 個重複貨號（後者覆蓋前者）")
        logger.info(f"訂貨主檔載入 {len(master)} 個貨號")
        return master

    # ── 分頁3：訂單明細（讀既有 + 追加）────────────────────
    def existing_detail_keys(self) -> set[tuple[str, str]]:
        """回傳既有明細的 (訂單編號, 貨號) 集合，供 idempotent 去重。"""
        ws = self._sh.worksheet(settings.ORDER_DETAIL_TAB)
        rows = ws.get_all_values()
        keys: set[tuple[str, str]] = set()
        for row in rows[1:]:
            order_no = _get(row, 1)
            sku = _get(row, 3)
            if order_no and sku:
                keys.add((order_no, sku))
        return keys

    def append_details(self, detail_rows: list[list]) -> int:
        """把明細列（已按 DETAIL_HEADERS 排好）追加到分頁3。回傳寫入列數。"""
        if not detail_rows:
            return 0
        ws = self._sh.worksheet(settings.ORDER_DETAIL_TAB)
        ws.append_rows(detail_rows, value_input_option="USER_ENTERED")
        logger.info(f"訂單明細追加 {len(detail_rows)} 列")
        return len(detail_rows)

    def read_details_for_date(self, date: str) -> list[list]:
        """讀某日的所有明細列（原始 row，供重算彙總）。"""
        ws = self._sh.worksheet(settings.ORDER_DETAIL_TAB)
        rows = ws.get_all_values()
        return [row for row in rows[1:] if _get(row, 0) == date]

    # ── 分頁2：每日彙總（重算 upsert）─────────────────────
    def upsert_summary(self, date: str, summary_rows: list[SummaryRow]) -> int:
        """把某日彙總寫進分頁2：先刪掉該日既有列，再追加新算的。回傳寫入列數。

        這樣重跑同一天不會累加、而是覆蓋（idempotent）。
        """
        ws = self._sh.worksheet(settings.ORDER_SUMMARY_TAB)
        all_rows = ws.get_all_values()
        header = all_rows[0] if all_rows else SUMMARY_HEADERS
        kept = [row for row in all_rows[1:] if _get(row, 0) != date]

        new_rows = [_summary_to_row(s) for s in summary_rows]
        final = [header] + kept + new_rows

        ws.clear()
        ws.update(final, value_input_option="USER_ENTERED")
        logger.info(f"每日彙總：{date} 寫入 {len(new_rows)} 列（保留其他日期 {len(kept)} 列）")
        return len(new_rows)

    def update_order_status(self, date: str, sku_code: str, status: str, order_time: str = "") -> bool:
        """回寫分頁2 某日某貨號的下單狀態/時間（cart_adder 用）。"""
        ws = self._sh.worksheet(settings.ORDER_SUMMARY_TAB)
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:], start=2):  # gspread 1-index，含表頭
            if _get(row, 0) == date and _get(row, 1) == sku_code:
                ws.update_cell(i, 10, status)      # 下單狀態（第10欄，1-index）
                if order_time:
                    ws.update_cell(i, 11, order_time)  # 下單時間
                return True
        logger.warning(f"回寫狀態找不到列：{date} / {sku_code}")
        return False


# ── helper ────────────────────────────────────────────────
def _get(row: list, idx: int) -> str:
    if idx >= len(row):
        return ""
    v = row[idx]
    return str(v).strip() if v is not None else ""


def _parse_num(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(str(s).replace("¥", "").replace(",", "").strip())
    except ValueError:
        return None


def _summary_to_row(s: SummaryRow) -> list:
    return [
        s.date,
        s.sku_code,
        s.code,
        s.short_name,
        s.spec1,
        s.spec2,
        s.total_qty,
        "" if s.cost_cny is None else s.cost_cny,
        "" if s.subtotal_cny is None else s.subtotal_cny,
        s.order_status,
        s.order_time,
    ]
