"""金流核對「刷新」流程：抓 1688 待付款訂單 → （可選）覆蓋 1688_DB。

預設 dry-run（commit=False）只回傳預覽（筆數/總實付/廠商清單），commit=True 才寫 Sheet。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from dataclasses import dataclass, field
from typing import Callable, Optional

from config import settings

from .pending_scraper import OrderRecord, scrape_pending_orders


@dataclass
class RefreshResult:
    records: list[OrderRecord]
    since_date: str
    status: str
    committed: bool = False
    updated_time: str = ""
    rows_written: int = 0

    @property
    def order_count(self) -> int:
        return len(self.records)

    @property
    def total_actual_pay(self) -> float:
        return round(sum(r.actual_pay for r in self.records), 2)

    @property
    def total_freight(self) -> float:
        return round(sum(r.freight for r in self.records), 2)

    @property
    def vendors(self) -> list[str]:
        seen: list[str] = []
        for r in self.records:
            if r.seller_company and r.seller_company not in seen:
                seen.append(r.seller_company)
        return seen


def refresh(
    since_date: Optional[str] = None,
    status: str = "waitbuyerpay",
    commit: bool = False,
    cookie_path: Optional[str] = None,
    headless: Optional[bool] = None,
    callback: Optional[Callable[[str], None]] = None,
) -> RefreshResult:
    """抓 1688 訂單並（可選）覆蓋 1688_DB。

    since_date：只留下單日 >= 此日的訂單（'YYYY-MM-DD'；預設今天）。傳 '' 或 None 且
      想抓全部時，明確傳 since_date=''。
    """
    if since_date is None:
        since_date = _dt.date.today().isoformat()
    cookie_path = cookie_path or str(settings.COOKIE_PATH)
    if headless is None:
        headless = settings.HEADLESS

    records = asyncio.run(scrape_pending_orders(
        cookie_path=cookie_path,
        status=status,
        since_date=since_date or None,
        headless=headless,
        callback=callback,
    ))
    result = RefreshResult(records=records, since_date=since_date or "", status=status)

    if commit:
        if not records:
            # 0 筆就覆蓋會清空整張 DB → 防呆：略過寫入
            if callback:
                callback("⚠️ 0 筆訂單，略過覆蓋（避免清空 1688_DB）")
            return result
        from .reconcile_db import ReconcileDB
        src = f"1688刷新 {status} 自{since_date or '全部'}"
        info = ReconcileDB().overwrite(records, source_name=src)
        result.committed = True
        result.updated_time = info["updated_time"]
        result.rows_written = info["rows"]
    return result


def format_preview(r: RefreshResult) -> str:
    """人可讀的預覽文字（GUI/CLI 共用）。"""
    lines = [
        f"📦 1688 {r.status} 訂單（下單日 >= {r.since_date or '全部'}）：{r.order_count} 筆",
        f"💰 實付合計 ¥{r.total_actual_pay:,.2f}（含運費 ¥{r.total_freight:,.2f}）",
        f"🏭 廠商 {len(r.vendors)} 家：",
    ]
    for r_ in r.records:
        lines.append(
            f"   {r_.create_date}  {r_.seller_company}  實付¥{r_.actual_pay:,.2f}"
            f"  運¥{r_.freight:,.2f}  #{r_.order_no}"
        )
    return "\n".join(lines)
