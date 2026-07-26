"""從雲端 Google Sheet 反向讀資料 → 灌進暫存 SQLite（#S104）。

背景：分析層原本讀本機 SQLite（Mac daemon 產）。但**真相在雲端 Sheet**、哪台都讀得到，
所以這支讓「沒有本機 SQLite 的機器（如公司 Windows）」也能跑分析——直接讀三賣場 Sheet
的原始日報分頁，灌成一個暫存 SQLite（用 storage_sqlite 同 schema），metrics/signals/change_log
完全不用改就能吃。

只需要 SA 憑證（讀那三張已分享的表），不需要蝦皮 cookie、不需要本機抓取過。

讀哪些分頁（欄序＝storage_sheet 寫入時的固定順序，前兩欄固定 日期/賣場）：
- `大盤日報_{YYYY}`            → shop_daily
- `商品日報_{YYYYMM}`         → product_daily（爆發/有看沒買/CTR 加總都靠它）
- `賣場廣告關鍵字_{YYYYMM}`   → shop_keyword_daily（顧問訊號，可缺）
- `自動選品商品_{YYYYMM}`     → gms_product_daily（顧問訊號，可缺）
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from . import storage_sqlite as ss
from .collector import FUNNEL_FIELDS, PRODUCT_FIELDS, SOURCE_FIELDS
from .gms_detail import GMS_FIELDS
from .shop_keyword import KW_FIELDS
from .sheet_util import open_sheet

_SHOP_DAILY_COLS = ss._SHOP_DAILY_COLS

# 哪些欄位是文字/整數（其餘 float）；跟 storage_sqlite 的型別判斷對齊
_INT_COLS = {"id"}
_TEXT_COLS = {"name", "status", "title", "type", "state", "campaign_name",
              "keyword", "match_type", "search_term", "product_id"}
_INT_ID_COLS = {"campaign_id"}


def _coerce(field: str, val: str):
    s = (val or "").strip()
    if s == "":
        return None
    if field in _TEXT_COLS:
        return s
    if field in _INT_COLS or field in _INT_ID_COLS:
        try:
            return int(float(s))
        except ValueError:
            return s
    # 數字欄：去逗號後轉 float
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _read_tab(sh, title: str, fields: list[str]) -> list[list]:
    """讀一個分頁，回原始 rows（含表頭）；分頁不存在回 []。"""
    try:
        ws = sh.worksheet(title)
    except Exception:  # WorksheetNotFound
        return []
    return ws.get_all_values()


def _rows_to_dicts(rows: list[list], fields: list[str], day_lo: str, day_hi: str) -> list[dict]:
    """把 [日期,賣場,*fields] 的資料列（濾日期窗）轉成 {shop,dt,*fields} dict。"""
    out = []
    for r in rows[1:]:  # 跳表頭
        if len(r) < 2:
            continue
        dt, shop = r[0].strip(), r[1].strip()
        if not dt or not (day_lo <= dt <= day_hi):
            continue
        rec = {"shop": shop, "dt": dt}
        for i, f in enumerate(fields):
            rec[f] = _coerce(f, r[2 + i] if 2 + i < len(r) else "")
        out.append(rec)
    return out


def _months_in_window(day: date, days_back: int) -> list[str]:
    lo = day - timedelta(days=days_back)
    months, cur = [], lo.replace(day=1)
    end = day.replace(day=1)
    while cur <= end:
        months.append(f"{cur:%Y%m}")
        # 跳到下個月
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def _upsert(con, table: str, cols: list[str], recs: list[dict]) -> int:
    if not recs:
        return 0
    all_cols = ["shop", "dt"] + cols
    sql = (f"INSERT OR REPLACE INTO {table} ({', '.join(all_cols)}) "
           f"VALUES ({', '.join('?' * len(all_cols))})")
    con.executemany(sql, [tuple(rec.get(c) for c in all_cols) for rec in recs])
    return len(recs)


def hydrate(db_path: str | Path, day: date, shop_sheet_ids: dict[str, str],
            days_back: int = 40) -> Path:
    """讀 shop_sheet_ids 裡每家的 Sheet → 灌 day 往前 days_back 天的資料進 db_path（暫存 SQLite）。

    days_back 預設 40：夠 metrics(7d)/signals(7d) 用，也涵蓋改動追蹤最近一個月的改動列。
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()   # 暫存 DB 每次重建，確保是雲端最新
    con = sqlite3.connect(str(db_path))
    con.executescript(ss.SCHEMA)

    day_lo = (day - timedelta(days=days_back)).isoformat()
    day_hi = day.isoformat()
    years = sorted({(day - timedelta(days=days_back)).year, day.year})
    months = _months_in_window(day, days_back)

    try:
        for shop, sid in shop_sheet_ids.items():
            if not sid:
                continue
            sh = open_sheet(sid)
            n_shop = n_prod = n_kw = n_gms = 0

            # 大盤日報（按年）
            for y in years:
                rows = _read_tab(sh, f"大盤日報_{y}", _SHOP_DAILY_COLS)
                recs = _rows_to_dicts(rows, _SHOP_DAILY_COLS, day_lo, day_hi)
                recs = [r for r in recs if r["shop"] == shop]
                n_shop += _upsert(con, "shop_daily", _SHOP_DAILY_COLS, recs)

            # 商品/關鍵字/自動選品（按月）
            for m in months:
                pr = _rows_to_dicts(_read_tab(sh, f"商品日報_{m}", PRODUCT_FIELDS),
                                    PRODUCT_FIELDS, day_lo, day_hi)
                pr = [r for r in pr if r["shop"] == shop]
                n_prod += _upsert(con, "product_daily", PRODUCT_FIELDS, pr)

                kw = _rows_to_dicts(_read_tab(sh, f"賣場廣告關鍵字_{m}", KW_FIELDS),
                                    KW_FIELDS, day_lo, day_hi)
                kw = [r for r in kw if r["shop"] == shop]
                n_kw += _upsert(con, "shop_keyword_daily", KW_FIELDS, kw)

                gm = _rows_to_dicts(_read_tab(sh, f"自動選品商品_{m}", GMS_FIELDS),
                                    GMS_FIELDS, day_lo, day_hi)
                gm = [r for r in gm if r["shop"] == shop]
                n_gms += _upsert(con, "gms_product_daily", GMS_FIELDS, gm)

            con.commit()
            logger.info(f"[{shop}] 從 Sheet 灌入：大盤 {n_shop} / 商品 {n_prod} / "
                        f"關鍵字 {n_kw} / 自動選品 {n_gms} 列")
    finally:
        con.close()
    return db_path
