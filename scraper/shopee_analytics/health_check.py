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

# 【全】ERP 每日庫存紀錄（inventory-sync 專案的最終產出；01:00 Mac cron 撈 ERP → 02:00
# Apps Script 匯入）。寬表一列一貨號、日期是欄頭（H 欄=最新、新→舊、保留 45 天），
# 故「H1 欄頭 == 今天」= 整條鏈端到端成功。SA 同一份（inventory-sync）。
ERP_SHEET_ID = "1KTGSgut9fpqr4xoHN42EpHo0321OUNbJSQv02cg1q08"
ERP_WIDE_TAB = "庫存日記錄_寬表"


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


# 各分頁標題模板 ↔ SQLite 表：驗 Sheet 是否漏寫用（%Y%m 按月、%Y 按年）
_SHEET_TAB_TABLES = [
    ("商品日報_{ym}", "product_daily"),
    ("規格日報_{ym}", "model_daily"),
    ("大盤日報_{y}", "shop_daily"),
    ("廣告日報_{ym}", "ad_daily"),
    ("自動選品商品_{ym}", "gms_product_daily"),
    ("賣場廣告關鍵字_{ym}", "shop_keyword_daily"),
]


def _sheet_missing_tabs(gc, sheet_id: str, shop: str, day: date, con) -> tuple[list[str], str]:
    """比對「SQLite 有資料的分頁」是否也寫進了 Google Sheet。

    回傳 (缺漏分頁清單, 錯誤訊息)。SQLite 有 N 列、Sheet 該日該賣場 < N → 判缺（429 半途中斷會這樣）。
    只查 SQLite 有料的分頁（跳過本來就 0 列的，避免誤報，如 lady 的賣場關鍵字）。
    """
    dt = day.isoformat()
    ym, y = f"{day:%Y%m}", f"{day:%Y}"
    try:
        sh = gc.open_by_key(sheet_id)
        existing = {w.title: w for w in sh.worksheets()}
    except Exception as e:  # noqa: BLE001 Sheet 讀不到＝無法驗證，回錯誤讓上層標註
        return [], f"Sheet 讀取失敗：{str(e)[:50]}"

    missing: list[str] = []
    for tab_tpl, table in _SHEET_TAB_TABLES:
        n_sql = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE shop=? AND dt=?", (shop, dt)
        ).fetchone()[0]
        if n_sql == 0:
            continue  # 本來就沒料 → 不需在 Sheet 出現
        title = tab_tpl.format(ym=ym, y=y)
        ws = existing.get(title)
        if ws is None:
            missing.append(title.split("_")[0])
            continue
        ab = ws.get_values("A:B")   # 只讀日期/賣場兩欄，輕量
        n_sheet = sum(1 for r in ab if len(r) >= 2 and r[0] == dt and r[1] == shop)
        if n_sheet < n_sql:
            missing.append(f"{title.split('_')[0]}({n_sheet}/{n_sql})")
    return missing, ""


def check_shopee(day: date) -> list[CheckResult]:
    """驗當天各賣場資料——SQLite 有（同步副本）+ Google Sheet 真的寫進去了（真相來源）。

    ⚠️ 只驗 SQLite 會有盲點：429 配額超限會「SQLite 有、Sheet 漏寫」→ 誤報全綠（#S104 lady 7/27）。
    故加驗 Sheet：SQLite 有料的分頁必須在 Sheet 也有同日同賣場的列，否則判 ❌。
    """
    from config import settings

    from .storage_sheet import _get_client

    results: list[CheckResult] = []
    if not DB_PATH.exists():
        return [CheckResult("蝦皮數據", False, "SQLite 不存在（從沒跑過？）")]
    con = sqlite3.connect(DB_PATH)
    try:
        gc = None
        try:
            gc = _get_client()
        except Exception as e:  # noqa: BLE001 拿不到 client → 只驗 SQLite，Sheet 標未驗
            logger.warning(f"健康點名取 Sheet client 失敗（只驗 SQLite）：{e}")
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
            sqlite_ok = n_prod > 0 and has_shop > 0
            detail = f"{day:%-m/%-d}份 商品{n_prod}/廣告{n_ad}/大盤{'有' if has_shop else '缺'}"

            # 加驗 Google Sheet（真相來源）——只在 SQLite 有料時才有意義
            sheet_ok = True
            sheet_id = settings.SHOPEE_ANALYTICS_SHEET_IDS.get(shop)
            if gc is not None and sqlite_ok and sheet_id:
                missing, err = _sheet_missing_tabs(gc, sheet_id, shop, day, con)
                if err:
                    detail += f"｜Sheet未驗({err})"       # 讀不到不判死，只註記
                elif missing:
                    sheet_ok = False
                    detail += f"｜⚠️Sheet漏寫：{','.join(missing)}"
                else:
                    detail += "｜Sheet齊"
            results.append(CheckResult(f"蝦皮數據({shop})", sqlite_ok and sheet_ok, detail))
    finally:
        con.close()
    return results


def check_erp() -> CheckResult:
    """驗 ERP 庫存寬表最新日期欄（H1）是不是「今天」——是＝01:00 撈料+02:00 匯入整條鏈成功。

    （1688 核對 daemon 不點名：Edwin 主動勾選觸發、當下就看得到結果，非被動排程。）
    """
    from .storage_sheet import _get_client

    try:
        ws = _get_client().open_by_key(ERP_SHEET_ID).worksheet(ERP_WIDE_TAB)
        h1 = (ws.get_values("H1") or [[""]])[0][0].strip()
    except Exception as e:  # noqa: BLE001
        return CheckResult("ERP 庫存", False, f"讀取失敗：{e}")
    today = date.today().isoformat()
    if h1 == today:
        return CheckResult("ERP 庫存", True, f"今日欄({h1})已更新")
    return CheckResult("ERP 庫存", False, f"最新欄還停在 {h1 or '空'}（應為 {today}）")


def run(day: date | None = None) -> bool:
    """跑所有點名 → 一則彙總通知。回傳整體是否全綠。"""
    day = day or (date.today() - timedelta(days=1))
    checks: list[CheckResult] = []
    checks += check_shopee(day)
    checks.append(check_erp())
    # 之後加：其他每日作業……（擴充點）

    all_ok = all(c.ok for c in checks)
    lines = [f"{'✅' if c.ok else '❌'} {c.name}：{c.detail}" for c in checks]
    summary = "\n".join(lines)
    logger.info(f"健康點名（{date.today()}）：{'；'.join(lines)}")

    # 1) 對話框視窗（停在螢幕直到點掉——不會像橫幅幾秒就消失）
    #    標題日期＝「點名當天」；各行 detail 自帶各自的資料日期（蝦皮=昨天份、ERP=今日欄）
    today = date.today()
    title = f"📊 數據點名 {today:%-m/%-d}：全部正常" if all_ok else f"⚠️ 數據點名 {today:%-m/%-d}：有異常"
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
