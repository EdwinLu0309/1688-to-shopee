"""三賣場「每日戰報」關鍵數運算層（#S104）。

紀律＝**少而精**：全店幾個關鍵數看方向，不做每商品多分析點（Edwin 拍板）。
資料源＝本機 SQLite（`shop_daily` + `product_daily`，有歷史）；純運算、好測。

8 個關鍵數（#S104 定案，之後加/拿掉只改 METRICS 這個 list）：
  成交額 / 成交訂單數 / 成交轉換率 / CTR / 訪客下單率 / 廣告花費 / 廣告ROAS / 廣告佔營收比
每個各帶「昨比」（vs 前一天）與「週比」（vs 7 天前）。

刻意的取數選擇：
- 成交額 / 商店訪客數 / 訪客下單買家 / 廣告花費·ROAS ← 取 `shop_daily` 官方大盤值
  （＝ Edwin 打開蝦皮大盤看到的同一個數，方便他核對）。
- 成交訂單數 / 曝光 / 點擊 ← `shop_daily` 沒有，用 `product_daily` 全店加總導出
  （CTR＝Σ點擊/Σ曝光、成交轉換率＝Σ成交訂單/商店訪客）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

# 賣場代號 → 中文顯示名（戰報表頭用）
SHOP_NAMES = {"nail": "美甲", "lady": "女裝", "baby": "嬰幼"}
SHOP_ORDER = ["nail", "lady", "baby"]


@dataclass
class Metric:
    key: str
    label: str          # 中文指標名
    kind: str           # money / int / pct / ratio
    direction: str      # up=越高越好 / down=越低越好 / neutral=中性（只看方向不染色）
    fn: Callable[[dict], float | None]  # 從 raw 聚合值算出這個指標
    note: str = ""      # 短說明（放戰報指標欄註記，可空）


def _ratio(num, den):
    """安全比值；分母為 0/None 回 None。"""
    if not den:
        return None
    if num is None:
        return None
    return num / den


# ── 8 個關鍵數（改這裡就能加/拿掉；順序＝戰報列順序）────────────────────
METRICS: list[Metric] = [
    Metric("confirmed_sales", "成交額", "money", "up",
           lambda r: r.get("confirmed_sales"), "已確認銷售額"),
    Metric("confirmed_orders", "成交訂單數", "int", "up",
           lambda r: r.get("sum_confirmed_orders"), "全店加總"),
    Metric("conv_rate", "成交轉換率", "pct", "up",
           lambda r: _ratio(r.get("sum_confirmed_orders"), r.get("shop_uv")),
           "成交訂單/訪客"),
    Metric("ctr", "CTR點擊率", "pct", "up",
           lambda r: _ratio(r.get("sum_clicks"), r.get("sum_impressions")),
           "商品卡點擊/曝光"),
    Metric("uv_to_placed", "訪客下單率", "pct", "up",
           lambda r: _ratio(r.get("placed_buyers"), r.get("shop_uv")),
           "下單買家/訪客"),
    Metric("ad_cost", "廣告花費", "money", "neutral",
           lambda r: r.get("ad_cost"), "所有廣告(含自動選品)"),
    Metric("ad_roi", "廣告ROAS", "ratio", "up",
           lambda r: r.get("ad_roi"), "廣告成交/花費"),
    Metric("ad_share", "廣告佔營收比", "pct", "down",
           lambda r: _ratio(r.get("ad_cost"), r.get("confirmed_sales")),
           "廣告花費/成交額"),
]


@dataclass
class Cell:
    """一個賣場×一個指標的一格：當日值 + 昨比 + 週比。"""
    value: float | None
    prev: float | None       # 前一天
    week: float | None       # 7 天前
    metric: Metric

    @property
    def dod(self) -> float | None:
        return _ratio((self.value - self.prev) if (self.value is not None and self.prev is not None) else None,
                      self.prev)

    @property
    def wow(self) -> float | None:
        return _ratio((self.value - self.week) if (self.value is not None and self.week is not None) else None,
                      self.week)


@dataclass
class ShopReport:
    shop: str
    name: str
    dt: date
    cells: dict[str, Cell] = field(default_factory=dict)   # metric.key -> Cell
    has_data: bool = False


@dataclass
class DailyReport:
    dt: date
    shops: list[ShopReport] = field(default_factory=list)


# ── SQLite 讀取 ──────────────────────────────────────────────────────

def _read_raw(con: sqlite3.Connection, shop: str, dt: str) -> dict | None:
    """讀某賣場某天的聚合原料；沒有大盤列 → None（那天沒抓到）。"""
    sd = con.execute(
        "SELECT confirmed_sales, shop_uv, placed_buyers, ad_cost, ad_gmv, ad_roi "
        "FROM shop_daily WHERE shop=? AND dt=?",
        (shop, dt),
    ).fetchone()
    if sd is None:
        return None
    raw: dict = {
        "confirmed_sales": sd[0],
        "shop_uv": sd[1],
        "placed_buyers": sd[2],
        "ad_cost": sd[3],
        "ad_gmv": sd[4],
        "ad_roi": sd[5],
    }
    prod = con.execute(
        "SELECT COALESCE(SUM(confirmed_orders),0), "
        "       COALESCE(SUM(product_card_impressions),0), "
        "       COALESCE(SUM(product_card_clicks),0) "
        "FROM product_daily WHERE shop=? AND dt=?",
        (shop, dt),
    ).fetchone()
    raw["sum_confirmed_orders"] = prod[0]
    raw["sum_impressions"] = prod[1]
    raw["sum_clicks"] = prod[2]
    return raw


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def compute_report(db_path: str | Path, day: date, shops: list[str] | None = None) -> DailyReport:
    """算 day 當天三賣場的戰報（值 + 昨比 + 週比）。

    shops 不給則用 SHOP_ORDER（會顯示所有三家，缺資料的以「—」呈現）。
    """
    shops = shops or SHOP_ORDER
    report = DailyReport(dt=day)
    con = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(con, "shop_daily"):
            for shop in shops:
                report.shops.append(ShopReport(shop=shop, name=SHOP_NAMES.get(shop, shop), dt=day))
            return report

        dt = day.isoformat()
        dt_prev = (day - timedelta(days=1)).isoformat()
        dt_week = (day - timedelta(days=7)).isoformat()

        for shop in shops:
            sr = ShopReport(shop=shop, name=SHOP_NAMES.get(shop, shop), dt=day)
            raw = _read_raw(con, shop, dt)
            raw_prev = _read_raw(con, shop, dt_prev)
            raw_week = _read_raw(con, shop, dt_week)
            sr.has_data = raw is not None
            for m in METRICS:
                sr.cells[m.key] = Cell(
                    value=m.fn(raw) if raw else None,
                    prev=m.fn(raw_prev) if raw_prev else None,
                    week=m.fn(raw_week) if raw_week else None,
                    metric=m,
                )
            report.shops.append(sr)
    finally:
        con.close()
    return report


# ── 呈現格式化（戰報與顧問共用）────────────────────────────────────────

def fmt_value(v: float | None, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "money":
        return f"{v:,.0f}"
    if kind == "int":
        return f"{v:,.0f}"
    if kind == "pct":
        return f"{v * 100:.2f}%"
    if kind == "ratio":
        return f"{v:.2f}"
    return str(v)


def fmt_delta(delta: float | None, direction: str) -> str:
    """把變化率格式化成「🟢▲5.3%」這種一眼可讀的字串。

    direction=up：漲=好(綠)、跌=壞(紅)；down：反過來；neutral：不染色只給箭頭。
    """
    if delta is None:
        return "—"
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "＝")
    pct = f"{abs(delta) * 100:.1f}%"
    if abs(delta) < 0.0005:
        return f"＝{pct}"
    if direction == "neutral":
        return f"{arrow}{pct}"
    good = (delta > 0) if direction == "up" else (delta < 0)
    return f"{'🟢' if good else '🔴'}{arrow}{pct}"
