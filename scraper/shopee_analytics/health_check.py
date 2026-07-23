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
    """macOS 通知中心（右上角橫幅；幾秒會消失，只當即時提示用）。"""
    script = f'display notification "{message}" with title "{title}"'
    if sound:
        script += ' sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except Exception as e:  # noqa: BLE001 通知失敗不該讓檢查本身掛掉
        logger.warning(f"macOS 通知失敗：{e}")


def alert_mac(title: str, message: str) -> None:
    """彈出對話框視窗——停在螢幕上直到點掉（Edwin 要「我再去看」的形態）。

    Popen 不等待：launchd 作業不用卡著等人點；視窗會一直留在螢幕。
    """
    msg = message.replace('"', "'")
    ttl = title.replace('"', "'")
    script = (
        f'display dialog "{msg}" with title "{ttl}" '
        'buttons {"知道了"} default button 1 with icon note'
    )
    try:
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"macOS 對話框失敗：{e}")


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
    summary = "\n".join(lines)
    logger.info(f"健康點名 {day}：{'；'.join(lines)}")

    # 1) 對話框視窗（停在螢幕直到點掉——不會像橫幅幾秒就消失）
    title = f"📊 今日數據正常（{day:%m/%d}）" if all_ok else f"⚠️ 數據異常（{day:%m/%d}）"
    alert_mac(title, summary)
    if not all_ok:
        notify_mac(title, "；".join(lines), sound=True)  # 異常再補一聲提示音

    # 2) 寫進 Sheet「抓取狀態」分頁（固定顯示點 + 歷史記錄；失敗不影響通知）
    try:
        _write_status_sheet(day, checks)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"抓取狀態寫入 Sheet 失敗：{e}")
    return all_ok


def _write_status_sheet(day: date, checks: list[CheckResult]) -> None:
    """把點名結果 append 到【Nail】蝦皮數據中心的「抓取狀態」分頁（一天一列）。"""
    from datetime import datetime

    from config import settings

    from .storage_sheet import _get_client

    sheet_id = settings.SHOPEE_ANALYTICS_SHEET_IDS.get("nail")
    if not sheet_id:
        return
    sh = _get_client().open_by_key(sheet_id)
    header = ["數據日期", "點名時間", "整體", "明細"]
    try:
        ws = sh.worksheet("抓取狀態")
    except Exception:
        ws = sh.add_worksheet(title="抓取狀態", rows=400, cols=6)
        ws.append_row(header, value_input_option="RAW")
    all_ok = all(c.ok for c in checks)
    detail = "；".join(f"{'✅' if c.ok else '❌'} {c.name}：{c.detail}" for c in checks)
    ws.append_row(
        [day.isoformat(), datetime.now().strftime("%Y-%m-%d %H:%M"),
         "✅ 正常" if all_ok else "❌ 異常", detail],
        value_input_option="RAW",
    )
    logger.info("抓取狀態已寫入 Sheet")


if __name__ == "__main__":
    import sys

    ok = run(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None)
    sys.exit(0 if ok else 1)
