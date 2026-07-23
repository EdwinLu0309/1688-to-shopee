"""每日數據健康點名（#S100）：驗「資料本身有沒有進來」，不是聽作業自己回報。

設計：排程失敗最危險的形態是「根本沒跑」——連失敗通知都不會有。
所以健康檢查獨立於抓取作業，每天 11:00 直接查 SQLite 有沒有昨天的資料：
有=✅、沒有（不管什麼原因）=❌，用 macOS 通知中心跳彙總通知。

之後 ERP/其他每日作業的點名可以加進 CHECKS，dashboard 要全貌也讀同一個結果。
"""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from loguru import logger

DB_PATH = Path("data/shopee_analytics/shopee_analytics.db")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def notify_mac(title: str, message: str, sound: bool = True) -> None:
    """macOS 通知中心（右上角橫幅）。"""
    script = f'display notification "{message}" with title "{title}"'
    if sound:
        script += ' sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except Exception as e:  # noqa: BLE001 通知失敗不該讓檢查本身掛掉
        logger.warning(f"macOS 通知失敗：{e}")


def check_shopee(day: date) -> list[CheckResult]:
    """驗 SQLite 裡有沒有 day 當天各賣場的資料（= 真相 Sheet 的同步副本）。"""
    from config import settings

    results: list[CheckResult] = []
    if not DB_PATH.exists():
        return [CheckResult("蝦皮數據", False, "SQLite 不存在（從沒跑過？）")]
    con = sqlite3.connect(DB_PATH)
    try:
        for shop in settings.SHOPEE_ANALYTICS_SHEET_IDS:
            dt = day.isoformat()
            n_prod = con.execute(
                "SELECT COUNT(*) FROM product_daily WHERE shop=? AND dt=?", (shop, dt)
            ).fetchone()[0]
            n_ad = con.execute(
                "SELECT COUNT(*) FROM ad_daily WHERE shop=? AND dt=?", (shop, dt)
            ).fetchone()[0]
            has_shop = con.execute(
                "SELECT COUNT(*) FROM shop_daily WHERE shop=? AND dt=?", (shop, dt)
            ).fetchone()[0]
            ok = n_prod > 0 and has_shop > 0
            detail = f"商品{n_prod}/廣告{n_ad}/大盤{'有' if has_shop else '缺'}"
            results.append(CheckResult(f"蝦皮數據({shop})", ok, detail))
    finally:
        con.close()
    return results


def run(day: date | None = None) -> bool:
    """跑所有點名 → 一則彙總通知。回傳整體是否全綠。"""
    day = day or (date.today() - timedelta(days=1))
    checks: list[CheckResult] = []
    checks += check_shopee(day)
    # 之後加：ERP 庫存、1688 核對 daemon 心跳……（CHECKS 擴充點）

    all_ok = all(c.ok for c in checks)
    lines = [f"{'✅' if c.ok else '❌'} {c.name}：{c.detail}" for c in checks]
    summary = "、".join(lines)
    logger.info(f"健康點名 {day}：{summary}")

    if all_ok:
        notify_mac(f"📊 今日數據正常（{day:%m/%d}）", summary, sound=False)
    else:
        notify_mac(f"⚠️ 數據異常（{day:%m/%d}）", summary, sound=True)
    return all_ok


if __name__ == "__main__":
    import sys

    ok = run(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None)
    sys.exit(0 if ok else 1)
