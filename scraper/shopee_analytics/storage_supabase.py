"""把分析結果寫進 personal-os-dashboard 的 Supabase（shopee schema，#S104 網頁版）。

架構＝跟 inventory 一樣：Python(service_role) 寫、Next.js dashboard(RLS) 讀。
用 httpx 直打 PostgREST（不加 supabase-py 依賴，跟 image_host 同風格）。
非 public schema 要帶 `Content-Profile: shopee`（寫）/`Accept-Profile: shopee`（讀）。

三塊：
- daily_metrics：每賣場當天 8 關鍵數（upsert on dt,shop）
- advice：當天 AI 店長顧問（upsert on dt）
- change_log：讀 status=tracking 的列、用 SQLite 算改動前後成效、PATCH 回

需 settings.POS_SUPABASE_URL + POS_SUPABASE_SERVICE_KEY（未設則整個略過、不報錯）。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import httpx
from loguru import logger

from . import change_log as CL
from .metrics import METRICS, DailyReport

_METRIC_KEYS = [m.key for m in METRICS]   # 8 個 = daily_metrics 的欄位


def _cfg() -> tuple[str, str] | None:
    from config import settings

    url = (settings.POS_SUPABASE_URL or "").rstrip("/")
    key = settings.POS_SUPABASE_SERVICE_KEY or ""
    if not url or not key:
        return None
    return url, key


def _headers(key: str, write: bool, upsert: bool = False) -> dict:
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if write:
        h["Content-Profile"] = "shopee"
        prefer = ["return=minimal"]
        if upsert:
            prefer.append("resolution=merge-duplicates")
        h["Prefer"] = ",".join(prefer)
    else:
        h["Accept-Profile"] = "shopee"
    return h


def enabled() -> bool:
    return _cfg() is not None


def write_report_and_advice(report: DailyReport, day: date, advice) -> bool:
    """寫 daily_metrics（三賣場）+ advice（當天一列）。回是否有寫。"""
    cfg = _cfg()
    if cfg is None:
        logger.info("未設 POS_SUPABASE_*，略過 Supabase 寫入")
        return False
    url, key = cfg
    dt = day.isoformat()

    # daily_metrics：每個有資料的賣場一列
    rows = []
    for sr in report.shops:
        if not sr.has_data:
            continue
        row = {"dt": dt, "shop": sr.shop, "updated_at": datetime.now().isoformat()}
        for k in _METRIC_KEYS:
            cell = sr.cells.get(k)
            row[k] = cell.value if cell else None
        rows.append(row)

    with httpx.Client(timeout=30) as client:
        if rows:
            r = client.post(
                f"{url}/rest/v1/daily_metrics?on_conflict=dt,shop",
                headers=_headers(key, write=True, upsert=True), json=rows,
            )
            r.raise_for_status()
            logger.info(f"Supabase daily_metrics 寫入 {len(rows)} 賣場（{dt}）")

        adv = {
            "dt": dt,
            "one_liner": advice.one_liner,
            "keep_good": advice.keep_good,
            "action_needed": advice.action_needed,
            "opportunity": advice.opportunity,
            "source": advice.source,
            "updated_at": datetime.now().isoformat(),
        }
        r = client.post(
            f"{url}/rest/v1/advice?on_conflict=dt",
            headers=_headers(key, write=True, upsert=True), json=[adv],
        )
        r.raise_for_status()
        logger.info(f"Supabase advice 寫入（{dt}，來源={advice.source}）")
    return True


def sync_change_log(db_path: str | Path, today: date | None = None) -> int:
    """讀 status=tracking 的改動列 → 用 SQLite 算前後成效 → PATCH 回。回處理列數。"""
    cfg = _cfg()
    if cfg is None:
        return 0
    url, key = cfg
    today = today or date.today()

    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{url}/rest/v1/change_log?status=eq.tracking"
            "&select=id,change_day,shop,target,metric_key",
            headers=_headers(key, write=False),
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return 0

        con = sqlite3.connect(str(db_path))
        processed = 0
        try:
            for row in rows:
                cd = row.get("change_day")
                ch = CL.Change(
                    row=0,
                    change_day=date.fromisoformat(cd) if cd else None,
                    shop=row.get("shop"),
                    target=row.get("target") or "",
                    metric_key=row.get("metric_key"),
                    raw=[],
                )
                d = CL.compute_change(con, ch, today)
                patch = {
                    "before3": d["before3"], "after3": d["after3"], "pct3": d["pct3"],
                    "before7": d["before7"], "after7": d["after7"], "pct7": d["pct7"],
                    "verdict": d["verdict"], "track_note": d["track_note"],
                    "computed_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }
                pr = client.patch(
                    f"{url}/rest/v1/change_log?id=eq.{row['id']}",
                    headers=_headers(key, write=True), json=patch,
                )
                pr.raise_for_status()
                processed += 1
        finally:
            con.close()
        logger.info(f"Supabase change_log 重算 {processed} 列")
        return processed


def write_all(report: DailyReport, day: date, advice, db_path: str | Path) -> bool:
    """一次寫齊：daily_metrics + advice + change_log 重算。"""
    if not enabled():
        return False
    write_report_and_advice(report, day, advice)
    try:
        sync_change_log(db_path, date.today())
    except Exception as e:  # noqa: BLE001 改動追蹤失敗不該擋掉戰報/顧問
        logger.warning(f"Supabase change_log 重算失敗（戰報/顧問已寫）：{e}")
    return True
