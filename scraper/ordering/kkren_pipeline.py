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
    updated_parcels: list[KkrenParcel] = field(default_factory=list)  # 舊單號、狀態有變
    committed: bool = False
    appended: int = 0
    updated: int = 0

    @property
    def scraped(self) -> int:
        return len(self.parcels)

    @property
    def new_count(self) -> int:
        return len(self.new_parcels)

    @property
    def update_count(self) -> int:
        return len(self.updated_parcels)


def _open(sheet_id: str | None = None):
    creds = Credentials.from_service_account_file(settings.ORDER_SHEET_SA_JSON, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id or settings.KKREN_SHEET_ID)


_STATUS_COL_A1 = "G"  # 物流狀態欄（第7欄）

import re as _re
_TS = _re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def _lead_ts(status: str) -> str:
    """抽狀態字串開頭的時間戳（'2026-07-13 10:24:17 已打包' → '2026-07-13 10:24:17'）供比新舊。"""
    m = _TS.search(status or "")
    return m.group(0) if m else ""


def _existing_index(sh) -> dict[str, tuple[int, str]]:
    """讀 Kkren_Data → {物流單號: (列號1-index, 現有物流狀態)}。"""
    ws = sh.worksheet(settings.KKREN_DATA_TAB)
    rows = ws.get_all_values()
    idx: dict[str, tuple[int, str]] = {}
    for i, r in enumerate(rows[1:], start=2):  # 第2列起（跳表頭），gspread 1-index
        if len(r) > _TRACKING_COL:
            tno = str(r[_TRACKING_COL]).strip()
            if tno:
                status = str(r[6]).strip() if len(r) > 6 else ""
                idx[tno] = (i, status)
    return idx


def refresh(
    since_days: int = 30,
    commit: bool = False,
    callback: Optional[Callable[[str], None]] = None,
) -> KkrenRefreshResult:
    """抓已出貨 → upsert 到 Kkren_Data：新物流單號 append、既有的更新最新物流狀態，
    舊列都不刪（累積、可長期追蹤舊運送單號）。"""
    parcels = scrape_shipped(since_days=since_days, callback=callback)
    result = KkrenRefreshResult(parcels=parcels)

    sh = _open()
    existing = _existing_index(sh)
    seen_now: set[str] = set()
    status_updates: list[dict] = []  # 既有單號的狀態更新（batch）
    for p in parcels:
        if p.tracking_no in seen_now:
            continue
        seen_now.add(p.tracking_no)
        if p.tracking_no in existing:
            row, cur_status = existing[p.tracking_no]
            # 只在「狀態時間真的往後推進」時才更新（避免把舊的較細文字用同時間點的格式蓋掉）
            if p.status and _lead_ts(p.status) > _lead_ts(cur_status):
                result.updated_parcels.append(p)
                status_updates.append({"range": f"{_STATUS_COL_A1}{row}", "values": [[p.status]]})
        else:
            result.new_parcels.append(p)

    if callback:
        callback(f"抓 {result.scraped} 包裹：新 {result.new_count} 筆、狀態更新 {result.update_count} 筆")

    if commit:
        ws = sh.worksheet(settings.KKREN_DATA_TAB)
        if status_updates:                                # 更新既有單號的最新狀態（不刪舊列）
            ws.batch_update(status_updates, value_input_option="USER_ENTERED")
            result.updated = len(status_updates)
        if result.new_parcels:                            # append 新單號
            ws.append_rows([p.to_row() for p in result.new_parcels],
                           value_input_option="USER_ENTERED")
            result.appended = result.new_count
        result.committed = True
        logger.info(f"Kkren_Data：append {result.appended} 新、更新 {result.updated} 狀態")
    return result


def format_preview(r: KkrenRefreshResult) -> str:
    lines = [f"📦 Kkren 已出貨：{r.scraped} 包裹｜新 {r.new_count} 筆、狀態更新 {r.update_count} 筆（舊列不刪）"]
    for p in r.new_parcels[:20]:
        lines.append(f"   {p.order_no}  {p.tracking_no}  {p.weight_kg}kg  {p.eta_wday}到  {p.status[:24]}")
    if r.new_count > 20:
        lines.append(f"   …還有 {r.new_count - 20} 筆")
    return "\n".join(lines)
