"""分析層 orchestrator（#S104）——三家抓完後跑這個，產三塊給 Edwin。

三塊（都寫進「戰報 Sheet」，預設＝Nail 數據表，可用 SHOPEE_DASHBOARD_SHEET_ID 換獨立表）：
  1. 每日戰報：一眼看三賣場 8 關鍵數 + 昨比/週比
  2. AI 店長顧問：每天一則白話結論 + 待辦
  3. 改動追蹤日誌：Edwin 填改動、系統算前後成效

正線：掛在 `shopee-collect-daily` 尾巴（三家都抓完、SQLite 有當天資料才跑）。
也可獨立 `shopee-analyze` 重跑（不重抓，純讀 SQLite 重算重寫）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

from . import advisor, change_log, daily_report
from .metrics import DailyReport, compute_report
from .sheet_util import open_sheet
from .signals import extract as extract_signals


@dataclass
class AnalysisResult:
    report: DailyReport
    advice: "advisor.Advice"
    digest: str


def run_analysis(day: date, db_path: str | Path, dashboard_sheet_id: str,
                 with_ai: bool = True) -> AnalysisResult:
    logger.info(f"分析層開跑（資料日 {day}）→ Sheet {dashboard_sheet_id}")
    report = compute_report(db_path, day)

    sh = open_sheet(dashboard_sheet_id)

    # 1) 每日戰報
    daily_report.write_report(sh, report)

    # 2) AI 店長顧問
    sigs = [extract_signals(db_path, sr.shop, sr.name, day, sr)
            for sr in report.shops if sr.has_data]
    digest = advisor.build_digest(report, sigs)
    advice = advisor.generate_advice(digest) if with_ai else advisor._fallback(digest)
    advisor.write_advisor(sh, day, advice)

    # 3) 改動追蹤日誌（掃 Edwin 填的列，算前後成效）
    change_log.update_change_log(sh, db_path, today=date.today())

    logger.info("分析層完成（戰報 + 顧問 + 改動追蹤）")
    return AnalysisResult(report=report, advice=advice, digest=digest)


def dashboard_sheet_id() -> str | None:
    """要寫哪張表：優先 settings.SHOPEE_DASHBOARD_SHEET_ID，退回 Nail 數據表。"""
    from config import settings

    sid = getattr(settings, "SHOPEE_DASHBOARD_SHEET_ID", "") or ""
    if sid:
        return sid
    return settings.SHOPEE_ANALYTICS_SHEET_IDS.get("nail")
