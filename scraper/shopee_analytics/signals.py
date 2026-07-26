"""跨表訊號抽取（#S104 Point 2 的原料）。

AI 顧問的價值在「跨表交叉」——把商品 × 廣告 × 大盤放一起，講出單看一張表看不出的話。
這裡把「值得今天注意的事」從 SQLite 撈成結構化訊號，再餵給 advisor 產白話建議。

刻意保守（寧缺）＋防禦（表可能不存在/空）：只抓真的踩到門檻的少數幾筆。
門檻集中在頂端常數，好調。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# ── 門檻（調這裡）──────────────────────────────────────────────
SURGE_MIN_ORDERS = 3        # 爆發：當天成交訂單至少這麼多才算數（濾雜訊）
SURGE_MULT = 2.0            # 且 ≥ 前 7 天日均的幾倍
DEADVIEW_MIN_UV = 50        # 有看沒買：當天訪客至少這麼多
KW_WASTE_MIN_COST = 30.0    # 關鍵字燒錢零轉換：花費門檻（元）
KW_WIN_MIN_ROAS = 5.0       # 高 ROAS 關鍵字/商品：ROAS 門檻
KW_WIN_MIN_COST = 10.0      # 且花費至少這麼多（濾掉花$1 ROAS 爆高的雜訊）
AD_SHARE_HIGH = 0.30        # 廣告佔營收比警戒線
WOW_DROP = 0.15             # 週比跌幅警戒（轉換/CTR/成交額）
TOPN = 5                    # 每類訊號最多幾筆


@dataclass
class ShopSignals:
    shop: str
    name: str
    surges: list[dict] = field(default_factory=list)        # 銷量爆發商品
    dead_views: list[dict] = field(default_factory=list)    # 有看沒買商品
    kw_waste: list[dict] = field(default_factory=list)      # 關鍵字燒錢零轉換
    kw_wins: list[dict] = field(default_factory=list)       # 高 ROAS 關鍵字（加碼機會）
    gms_wins: list[dict] = field(default_factory=list)      # 自動選品高 ROAS 商品
    flags: list[str] = field(default_factory=list)          # 大盤層警示（白話）

    @property
    def empty(self) -> bool:
        return not (self.surges or self.dead_views or self.kw_waste
                    or self.kw_wins or self.gms_wins or self.flags)


def _has(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _surges(con, shop, dt, dt_wkstart):
    if not _has(con, "product_daily"):
        return []
    rows = con.execute(
        """
        SELECT p.id, p.name, p.confirmed_orders, p.uv,
               (SELECT AVG(p2.confirmed_orders) FROM product_daily p2
                WHERE p2.shop=p.shop AND p2.id=p.id AND p2.dt>=? AND p2.dt<?) AS avg7
        FROM product_daily p
        WHERE p.shop=? AND p.dt=? AND COALESCE(p.confirmed_orders,0) >= ?
        ORDER BY p.confirmed_orders DESC
        """,
        (dt_wkstart, dt, shop, dt, SURGE_MIN_ORDERS),
    ).fetchall()
    out = []
    for pid, name, orders, uv, avg7 in rows:
        if avg7 and avg7 > 0 and orders >= SURGE_MULT * avg7:
            out.append({"id": pid, "name": name, "orders": orders,
                        "avg7": round(avg7, 1), "uv": uv})
        elif not avg7 and orders >= SURGE_MIN_ORDERS * 2:  # 前 7 天沒資料的新爆品
            out.append({"id": pid, "name": name, "orders": orders, "avg7": None, "uv": uv})
        if len(out) >= TOPN:
            break
    return out


def _dead_views(con, shop, dt):
    if not _has(con, "product_daily"):
        return []
    rows = con.execute(
        """
        SELECT id, name, uv, add_to_cart_units
        FROM product_daily
        WHERE shop=? AND dt=? AND COALESCE(uv,0) >= ?
          AND COALESCE(confirmed_orders,0) = 0
        ORDER BY uv DESC LIMIT ?
        """,
        (shop, dt, DEADVIEW_MIN_UV, TOPN),
    ).fetchall()
    return [{"id": r[0], "name": r[1], "uv": r[2], "atc": r[3]} for r in rows]


def _kw_waste(con, shop, dt):
    if not _has(con, "shop_keyword_daily"):
        return []
    rows = con.execute(
        """
        SELECT keyword, search_term, cost, click
        FROM shop_keyword_daily
        WHERE shop=? AND dt=? AND COALESCE(cost,0) >= ?
          AND COALESCE(conversions,0) = 0
        ORDER BY cost DESC LIMIT ?
        """,
        (shop, dt, KW_WASTE_MIN_COST, TOPN),
    ).fetchall()
    return [{"keyword": r[0], "term": r[1], "cost": round(r[2] or 0, 1), "click": r[3]}
            for r in rows]


def _kw_wins(con, shop, dt):
    if not _has(con, "shop_keyword_daily"):
        return []
    rows = con.execute(
        """
        SELECT keyword, roas, cost, conversions
        FROM shop_keyword_daily
        WHERE shop=? AND dt=? AND COALESCE(roas,0) >= ? AND COALESCE(cost,0) >= ?
        ORDER BY roas DESC LIMIT ?
        """,
        (shop, dt, KW_WIN_MIN_ROAS, KW_WIN_MIN_COST, TOPN),
    ).fetchall()
    return [{"keyword": r[0], "roas": round(r[1] or 0, 1),
             "cost": round(r[2] or 0, 1), "conv": r[3]} for r in rows]


def _gms_wins(con, shop, dt):
    if not _has(con, "gms_product_daily"):
        return []
    rows = con.execute(
        """
        SELECT name, roas, cost, conversions
        FROM gms_product_daily
        WHERE shop=? AND dt=? AND COALESCE(roas,0) >= ? AND COALESCE(cost,0) >= ?
        ORDER BY roas DESC LIMIT ?
        """,
        (shop, dt, KW_WIN_MIN_ROAS, KW_WIN_MIN_COST, TOPN),
    ).fetchall()
    return [{"name": r[0], "roas": round(r[1] or 0, 1),
             "cost": round(r[2] or 0, 1), "conv": r[3]} for r in rows]


def extract(db_path: str | Path, shop: str, name: str, day: date, shop_report=None) -> ShopSignals:
    """撈某賣場某天的所有訊號。shop_report＝該賣場 metrics.ShopReport（拿大盤層警示）。"""
    sig = ShopSignals(shop=shop, name=name)
    con = sqlite3.connect(str(db_path))
    try:
        if not _has(con, "shop_daily"):
            return sig
        dt = day.isoformat()
        dt_wkstart = (day - timedelta(days=7)).isoformat()
        sig.surges = _surges(con, shop, dt, dt_wkstart)
        sig.dead_views = _dead_views(con, shop, dt)
        sig.kw_waste = _kw_waste(con, shop, dt)
        sig.kw_wins = _kw_wins(con, shop, dt)
        sig.gms_wins = _gms_wins(con, shop, dt)
    finally:
        con.close()

    # 大盤層警示（從 metrics 算好的 cell 讀，不重算）
    if shop_report is not None:
        sig.flags = _shop_flags(shop_report)
    return sig


def _shop_flags(sr) -> list[str]:
    from .metrics import fmt_value

    flags: list[str] = []
    c = sr.cells

    ad_share = c.get("ad_share")
    if ad_share and ad_share.value is not None and ad_share.value >= AD_SHARE_HIGH:
        flags.append(f"廣告佔營收比 {fmt_value(ad_share.value, 'pct')}（偏高，>{int(AD_SHARE_HIGH*100)}%）")

    conv = c.get("conv_rate")
    if conv and conv.wow is not None and conv.wow <= -WOW_DROP:
        flags.append(f"成交轉換率週比掉 {abs(conv.wow)*100:.0f}%（{fmt_value(conv.value,'pct')}）")

    ctr = c.get("ctr")
    if ctr and ctr.wow is not None and ctr.wow <= -WOW_DROP:
        flags.append(f"CTR 週比掉 {abs(ctr.wow)*100:.0f}%（{fmt_value(ctr.value,'pct')}）")

    sales = c.get("confirmed_sales")
    if sales and sales.wow is not None and sales.wow <= -WOW_DROP:
        flags.append(f"成交額週比掉 {abs(sales.wow)*100:.0f}%")

    roi = c.get("ad_roi")
    if roi and roi.value is not None and roi.value < 1 and (c.get("ad_cost") and (c["ad_cost"].value or 0) > 0):
        flags.append(f"廣告 ROAS {fmt_value(roi.value,'ratio')}（<1，廣告在虧）")

    return flags
