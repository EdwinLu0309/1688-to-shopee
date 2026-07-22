"""常駐監聽 daemon — ERP 式「雲端打勾 → Mac 常駐監聽 → 自動抓 1688 → 寫中央檔」。

架構（見 CLAUDE.md「金流核對刷新」+ mac 常駐主機）：
- Edwin 在**消費表**（金額核對表/到貨表…）的「🔄刷新控制」分頁打勾 → 旗標格變 TRUE。
- 本 daemon 每 POLL_SEC 秒用 SA 輪詢各「口」（trigger）的旗標格。
- 看到打勾 → 抓對應帳號的 1688 訂單 → 覆蓋**中央「1688訂單資料」檔**（單一來源）
  → 把旗標清回 FALSE、回寫「狀態 / 最後更新時間」。
- 消費表用 IMPORTRANGE 唯讀引用中央檔，daemon 不必寫消費表的資料區（繞過共用碟寫入限制）。

config 驅動：新增賣場＝在 JOBS 加一列 + 那張表加個「口」，不用改邏輯、不用多開 daemon。
多口共用同一 job（如金額核對表 + 到貨表都要更新美甲中央檔）→ 任一口打勾就更新一次（去重）。

用法：
  python -m scraper.ordering.reconcile_daemon setup   # 在各口建「🔄刷新控制」分頁+勾選格
  python -m scraper.ordering.reconcile_daemon once     # 跑一輪（測試）
  python -m scraper.ordering.reconcile_daemon run      # 常駐輪詢（LaunchAgent 跑這個）
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import sys
import time

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

from config import settings

from .pending_scraper import scrape_pending_orders
from .reconcile_db import ReconcileDB, _SCOPES

POLL_SEC = 20          # 輪詢間隔（秒）
CONTROL_TAB = "🔄刷新控制"

# ── 控制分頁格位（1-index 給 gspread；0-index 給 API）──
# B1 旗標(checkbox) / B2 核對日期 / B3 狀態(回寫) / B4 最後更新(回寫) / B5 訂單狀態 / B6 cookie 狀態(回寫)
CELL_FLAG = "B1"
CELL_DATE = "B2"
CELL_STATUS = "B3"
CELL_TIME = "B4"
CELL_ORDERSTATUS = "B5"
CELL_COOKIE = "B6"

LABELS = [
    ["刷新開關（打勾觸發）", False],
    ["核對日期（下單日>=，空=今天）", ""],
    ["狀態（系統回寫）", ""],
    ["最後更新（系統回寫）", ""],
    ["訂單狀態（waitbuyerpay/all）", "waitbuyerpay"],
    ["🔑 Cookie 狀態（系統回寫）", ""],
]

# cookie 健康檢查排程（見 cookie_health.py）：每次都實打探測（探測才是權威，讀檔案會誤報）
COOKIE_CHECK_SEC = 6 * 3600      # 每 6h 探測各 cookie 一次（page=1 極輕量）→ 寫狀態格

# ── Jobs：一個 job = 一個帳號 + 一個抓取狀態 + 寫進哪張表的 1688_DB + 觸發口 ──
# 直接寫消費表自己的 1688_DB（日期分頁活公式 XLOOKUP 它，即時生效、免 IMPORTRANGE 授權）。
# 金額核對＝抓待付款；到貨＝抓待收貨（不同表、不同狀態、不同資料，各寫各的，不共用中央檔）。
ARRIVAL_SHEET_ID = "1Ojmd8-2VtX1qloCP5xmrncNRlQajhHuMgtXO-VffQ_A"  # 【Nail】2-2 商品到貨記錄

JOBS = [
    {
        "name": "nail-金額核對",
        "cookie": str(settings.COOKIE_PATH_NAIL),
        "target_sheet_id": settings.RECONCILE_SHEET_ID,   # ① 金額核對表
        "target_tab": settings.RECONCILE_DB_TAB,          # 1688_DB
        "default_status": "waitbuyerpay",                 # 待付款
        "arrival": False,                                 # 26 欄金額版
        "triggers": [
            {"sheet_id": settings.RECONCILE_SHEET_ID, "label": "金額核對表"},
        ],
    },
    {
        "name": "nail-到貨核對",
        "cookie": str(settings.COOKIE_PATH_NAIL),
        "target_sheet_id": ARRIVAL_SHEET_ID,              # ② 到貨表
        "target_tab": "1688_DB",
        "default_status": "waitbuyerreceive",             # 待收貨（才有運單號）
        "arrival": True,                                  # 50 欄到貨版（運單號在 AF）
        "also_kkren": True,                               # 同時刷 Kkren 已出貨 → Kkren_Data
        "triggers": [
            {"sheet_id": ARRIVAL_SHEET_ID, "label": "到貨表"},
        ],
    },
]

# ── Lady 賣場（帳號 joyslunailshop = cookies.json；到貨同 Kkren 中繼 181lP）──
# 先由 Edwin 複製 Nail 的 2-1 進貨金額 / 2-2 到貨記錄 → Lady 版並分享 SA，
# 把副本 ID 填進下面兩個常數即自動掛上（空字串＝略過，不影響現行 daemon）。
LADY_RECONCILE_SHEET_ID = "1B2WwAhJb84Ykc5tKIIYHr419HAd66ZSSA5dQBQJsDGo"  # 【Lady】2-1 進貨金額記錄
LADY_ARRIVAL_SHEET_ID = "1befHjwN434vLtjJplqGSxOBT-7D6IVJqfgZUK1N1Rww"    # 【Lady】2-2 商品到貨記錄

if LADY_RECONCILE_SHEET_ID:
    JOBS.append({
        "name": "lady-金額核對",
        "cookie": str(settings.COOKIE_PATH),              # 服飾 joyslunailshop
        "target_sheet_id": LADY_RECONCILE_SHEET_ID,
        "target_tab": "1688_DB",
        "default_status": "waitbuyerpay",
        "arrival": False,
        "triggers": [
            {"sheet_id": LADY_RECONCILE_SHEET_ID, "label": "Lady金額核對表"},
        ],
    })
if LADY_ARRIVAL_SHEET_ID:
    JOBS.append({
        "name": "lady-到貨核對",
        "cookie": str(settings.COOKIE_PATH),              # 服飾 joyslunailshop
        "target_sheet_id": LADY_ARRIVAL_SHEET_ID,
        "target_tab": "1688_DB",
        "default_status": "waitbuyerreceive",
        "arrival": True,
        "also_kkren": True,                               # 同 Kkren 中繼（共用）
        "triggers": [
            {"sheet_id": LADY_ARRIVAL_SHEET_ID, "label": "Lady到貨表"},
        ],
    })

# ── Baby 賣場（帳號 luwei03090826 = cookies_baby.json；到貨走 Kkren 但不同帳號，先不接）──
# cookies_baby.json 由 Edwin 之後登入 luwei03090826 產生（先建 job/打勾格，登入後即生效）。
BABY_RECONCILE_SHEET_ID = "1Agsc87285Epdnr4rInaF6eafvtn8ewEFrQr_zdodt48"   # 【Baby】2-1 進貨金額記錄
BABY_ARRIVAL_SHEET_ID = "18goabC7RiKPMRDcRmCO1X_8pI_Kh5WUASdHoictvONs"     # 【Baby】2-2 商品到貨記錄
COOKIE_PATH_BABY = settings.COOKIE_PATH.parent / "cookies_baby.json"

if BABY_RECONCILE_SHEET_ID:
    JOBS.append({
        "name": "baby-金額核對",
        "cookie": str(COOKIE_PATH_BABY),                  # luwei03090826
        "target_sheet_id": BABY_RECONCILE_SHEET_ID,
        "target_tab": "1688_DB",
        "default_status": "waitbuyerpay",
        "arrival": False,
        "triggers": [
            {"sheet_id": BABY_RECONCILE_SHEET_ID, "label": "Baby金額核對表"},
        ],
    })
if BABY_ARRIVAL_SHEET_ID:
    JOBS.append({
        "name": "baby-到貨核對",
        "cookie": str(COOKIE_PATH_BABY),                  # luwei03090826
        "target_sheet_id": BABY_ARRIVAL_SHEET_ID,
        "target_tab": "1688_DB",
        "default_status": "waitbuyerreceive",
        "arrival": True,
        "also_kkren": False,   # ★Baby 的 Kkren 是「不同帳號」→ 暫不刷共用中繼，待另接 Baby Kkren
        "triggers": [
            {"sheet_id": BABY_ARRIVAL_SHEET_ID, "label": "Baby到貨表"},
        ],
    })


def _client():
    creds = Credentials.from_service_account_file(settings.ORDER_SHEET_SA_JSON, scopes=_SCOPES)
    return gspread.authorize(creds)


def _a1_rc(a1: str) -> tuple[int, int]:
    """'B3' → (row0, col0)。僅支援單字母欄。"""
    col = ord(a1[0].upper()) - ord("A")
    row = int(a1[1:]) - 1
    return row, col


# ── setup：在每個口建「🔄刷新控制」分頁 + 勾選框 ──
def setup(gc=None) -> None:
    gc = gc or _client()
    for job in JOBS:
        for trig in job["triggers"]:
            sh = gc.open_by_key(trig["sheet_id"])
            try:
                ws = sh.worksheet(CONTROL_TAB)
                logger.info(f"[{trig['label']}] 控制分頁已存在，更新標籤")
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title=CONTROL_TAB, rows=10, cols=3)
                logger.info(f"[{trig['label']}] 已建控制分頁")
            # 寫標籤 + 預設值（只動 A1:B6，不碰其他分頁）；訂單狀態用該 job 的預設
            labels = [list(x) for x in LABELS]
            labels[4][1] = job.get("default_status", "waitbuyerpay")   # B5 訂單狀態
            ws.update([[lab, val] for lab, val in labels], "A1:B6",
                      value_input_option="USER_ENTERED")
            ws.format("A1:A6", {"textFormat": {"bold": True}})
            # B1 設成勾選框
            r, c = _a1_rc(CELL_FLAG)
            sh.batch_update({"requests": [{
                "setDataValidation": {
                    "range": {"sheetId": ws.id, "startRowIndex": r, "endRowIndex": r + 1,
                              "startColumnIndex": c, "endColumnIndex": c + 1},
                    "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True},
                }}]})
            logger.info(f"[{trig['label']}] 控制分頁就緒（B1 打勾即觸發）")


# ── 執行一個 job：抓 1688 → 覆蓋中央檔 ──
def _run_job(job: dict, since_date: str, order_status: str) -> str:
    """回傳給人看的狀態字串。"""
    records = asyncio.run(scrape_pending_orders(
        cookie_path=job["cookie"], status=order_status,
        since_date=since_date or None, headless=True,
    ))
    if not records:
        return f"⚠️ 0 筆（{order_status}，下單日>={since_date or '全部'}）→ 未更新（避免清空 1688_DB）"
    arrival = job.get("arrival", False)
    db = ReconcileDB(sheet_id=job["target_sheet_id"], tab=job["target_tab"])
    info = db.overwrite(records, source_name=f"daemon {job['name']} {order_status}", arrival=arrival)
    if arrival:
        n_track = sum(1 for r in records if r.tracking_no)
        msg = f"✅ {info['orders']} 訂單／{n_track} 有運單號"
        # 到貨口同時刷 Kkren 已出貨 → Kkren_Data（去重 append）
        if job.get("also_kkren"):
            try:
                from .kkren_pipeline import refresh as kkren_refresh
                kr = kkren_refresh(since_days=30, commit=True)
                msg += f"；Kkren 新{kr.appended}/更新{kr.updated}"
            except Exception as e:
                msg += f"；⚠️Kkren 失敗：{str(e)[:40]}"
        return f"{msg}（{info['updated_time']}）"
    total = round(sum(r.actual_pay for r in records), 2)
    return f"✅ {info['orders']} 筆訂單／實付¥{total:,.2f}（{info['updated_time']}）"


# ── 一輪輪詢：檢查所有口，觸發的 job 跑一次 ──
def run_once(gc=None) -> int:
    gc = gc or _client()
    fired = 0
    for job in JOBS:
        # 收集這個 job 中被打勾的口
        triggered = []
        for trig in job["triggers"]:
            try:
                sh = gc.open_by_key(trig["sheet_id"])
                ws = sh.worksheet(CONTROL_TAB)
            except Exception:
                continue  # 控制分頁還沒建
            flag = ws.acell(CELL_FLAG).value
            if str(flag).upper() in ("TRUE", "1", "是", "V", "✓"):
                triggered.append((trig, sh, ws))
        if not triggered:
            continue
        # 去重：同 job 只跑一次，用第一個口的參數
        _, _, ws0 = triggered[0]
        since_date = (ws0.acell(CELL_DATE).value or "").strip()
        order_status = (ws0.acell(CELL_ORDERSTATUS).value or "").strip() \
            or job.get("default_status", "waitbuyerpay")
        # 先把所有觸發口標「執行中」並清旗標（避免重複觸發）
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for _, _, ws in triggered:
            ws.update_acell(CELL_FLAG, False)
            ws.update_acell(CELL_STATUS, "⏳ 抓取中…")
        logger.info(f"[{job['name']}] 觸發（{len(triggered)} 口）：status={order_status} date={since_date or '今天以外全部' if since_date=='' else since_date}")
        try:
            msg = _run_job(job, since_date, order_status)
        except Exception as e:
            msg = f"❌ 失敗：{e}"
            logger.exception(f"[{job['name']}] job 失敗")
        # session 過期是最常見的失敗 → 順手把 cookie 狀態格標紅（含重登提示），一眼可見
        cookie_expired = any(k in msg for k in ("SESSION_EXPIRED", "Session过期", "失效", "登入頁"))
        for _, _, ws in triggered:
            ws.update_acell(CELL_STATUS, msg)
            ws.update_acell(CELL_TIME, now)
            if cookie_expired:
                try:
                    from .cookie_health import status_line
                    ws.update_acell(CELL_COOKIE, status_line(job["cookie"], probe_dead=True))
                except Exception:
                    pass
        fired += 1
        logger.info(f"[{job['name']}] 完成：{msg}")
    return fired


# ── cookie 健康檢查：讀到期日（+ 可選探測）→ 寫各控制分頁的「🔑 Cookie 狀態」──
def check_cookies(gc=None, probe: bool = False) -> None:
    gc = gc or _client()
    from collections import defaultdict
    from .cookie_health import probe_alive, status_line
    # 同一 cookie 被多口共用 → 只探測一次，寫進所有用它的控制分頁
    cookie_to_ws: dict[str, list] = defaultdict(list)
    for job in JOBS:
        for trig in job["triggers"]:
            try:
                ws = gc.open_by_key(trig["sheet_id"]).worksheet(CONTROL_TAB)
            except Exception:
                continue  # 控制分頁還沒建
            cookie_to_ws[job["cookie"]].append(ws)
    for cookie_path, wss in cookie_to_ws.items():
        dead = None
        if probe and __import__("pathlib").Path(cookie_path).exists():
            try:
                alive, _ = asyncio.run(probe_alive(cookie_path))
                dead = (alive is False)
            except Exception as e:
                logger.warning(f"cookie 探測失敗（不判死）：{cookie_path} {e}")
        line = status_line(cookie_path, probe_dead=dead)
        for ws in wss:
            try:
                ws.update([["🔑 Cookie 狀態（系統回寫）", line]], "A6:B6",
                          value_input_option="USER_ENTERED")
            except Exception as e:
                logger.warning(f"寫 cookie 狀態失敗：{e}")
        logger.info(f"[cookie] {cookie_path} → {line}")


def run_forever() -> None:
    logger.info(f"daemon 啟動，每 {POLL_SEC}s 輪詢 {sum(len(j['triggers']) for j in JOBS)} 個口")
    gc = _client()
    last_cookie = 0.0    # 上次探測+寫 cookie 狀態格（0＝啟動即先做一次）
    while True:
        try:
            run_once(gc)
            now = time.time()
            if now - last_cookie >= COOKIE_CHECK_SEC:
                check_cookies(gc, probe=True)
                last_cookie = now
        except Exception as e:
            logger.exception(f"輪詢例外（續跑）：{e}")
        time.sleep(POLL_SEC)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "setup":
        setup()
    elif cmd == "once":
        n = run_once()
        print(f"本輪觸發 {n} 個 job")
    elif cmd == "cookies":
        # 立即檢查並寫各控制分頁的 cookie 狀態（帶 probe 參數＝連 1688 探測）
        probe = len(sys.argv) > 2 and sys.argv[2] == "probe"
        check_cookies(probe=probe)
    elif cmd == "run":
        run_forever()
    else:
        print("用法：setup | once | cookies [probe] | run")
        sys.exit(1)


if __name__ == "__main__":
    main()
