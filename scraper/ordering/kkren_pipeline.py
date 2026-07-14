"""Kkren 刷新流程：抓已出貨包裹 → 去重 append 到 Kkren 中繼表的 Kkren_Data 分頁。

去重 key＝物流單號（parcels[].trackingNo，每包裹唯一）。只加中繼表還沒有的新包裹
（比照 Edwin「只抓還沒建立過的新的」）。預設 dry-run，commit=True 才寫。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

from config import settings

from .kkren_scraper import KKREN_HEADERS, KkrenParcel, scrape_shipped

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_TRACKING_COL = 4  # Kkren_Data 物流單號在第 5 欄（0-index 4）


@dataclass
class KkrenRefreshResult:
    parcels: list[KkrenParcel]
    new_parcels: list[KkrenParcel] = field(default_factory=list)
    committed: bool = False
    appended: int = 0

    @property
    def scraped(self) -> int:
        return len(self.parcels)

    @property
    def new_count(self) -> int:
        return len(self.new_parcels)


def _open(sheet_id: str | None = None):
    creds = Credentials.from_service_account_file(settings.ORDER_SHEET_SA_JSON, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id or settings.KKREN_SHEET_ID)


def _existing_tracking_nos(sh) -> set[str]:
    ws = sh.worksheet(settings.KKREN_DATA_TAB)
    rows = ws.get_all_values()
    seen: set[str] = set()
    for r in rows[1:]:  # 跳表頭
        if len(r) > _TRACKING_COL:
            tno = str(r[_TRACKING_COL]).strip()
            if tno:
                seen.add(tno)
    return seen


def refresh(
    since_days: int = 30,
    commit: bool = False,
    callback: Optional[Callable[[str], None]] = None,
) -> KkrenRefreshResult:
    """抓已出貨 → 去重（比對 Kkren_Data 既有物流單號）→（可選）append 新的。"""
    parcels = scrape_shipped(since_days=since_days, callback=callback)
    result = KkrenRefreshResult(parcels=parcels)

    sh = _open()
    existing = _existing_tracking_nos(sh)
    # 去重：只留中繼表還沒有的物流單號（同批也去重）
    seen_now: set[str] = set()
    for p in parcels:
        if p.tracking_no in existing or p.tracking_no in seen_now:
            continue
        seen_now.add(p.tracking_no)
        result.new_parcels.append(p)

    if callback:
        callback(f"抓到 {result.scraped} 包裹，其中 {result.new_count} 筆是新的（未建立）")

    if commit and result.new_parcels:
        ws = sh.worksheet(settings.KKREN_DATA_TAB)
        ws.append_rows([p.to_row() for p in result.new_parcels],
                       value_input_option="USER_ENTERED")
        result.committed = True
        result.appended = result.new_count
        logger.info(f"Kkren_Data append {result.appended} 筆新包裹")
    return result


def format_preview(r: KkrenRefreshResult) -> str:
    lines = [f"📦 Kkren 已出貨：{r.scraped} 包裹，其中 {r.new_count} 筆新（未建立）"]
    for p in r.new_parcels[:20]:
        lines.append(f"   {p.order_no}  {p.tracking_no}  {p.weight_kg}kg  {p.eta_wday}到  {p.status[:24]}")
    if r.new_count > 20:
        lines.append(f"   …還有 {r.new_count - 20} 筆")
    return "\n".join(lines)
