"""抓取一天份的三張核心表，回傳結構化資料 + raw JSON 快照。

正線用法：每天 10:30 抓「前一天」（period=yesterday 已驗證）。
任意歷史日期的 period 值尚未探勘，collect_day 對非昨天的日期
仍會帶 period=yesterday + 該日 start/end epoch — 是否被蝦皮接受待驗證。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from loguru import logger

from .client import ShopeeDataClient

PAGE_SIZE = 100

# 商品層落地欄位（49 欄挑核心，其餘留在 raw 快照裡隨時可回撈）
PRODUCT_FIELDS = [
    "id", "name", "status",
    "product_card_impressions", "product_card_clicks", "ctr", "search_clicks",
    "uv", "pv", "bounce_rate", "likes",
    "add_to_cart_units", "add_to_cart_buyers",
    "placed_sales", "placed_units", "placed_buyers", "placed_orders",
    "paid_sales", "paid_units", "paid_buyers", "paid_orders",
    "confirmed_sales", "confirmed_units", "confirmed_buyers", "confirmed_orders",
    "placed_order_conversion_rate", "confirmed_order_conversion_rate",
    "uv_to_add_to_cart_rate", "uv_to_placed_buyers_rate",
]

MODEL_FIELDS = [
    "id", "name", "status",
    "add_to_cart_units", "add_to_cart_buyers",
    "placed_sales", "placed_units", "placed_buyers",
    "paid_sales", "paid_units", "paid_buyers",
    "confirmed_sales", "confirmed_units", "confirmed_buyers",
]

# 大盤（funnel + key-metrics + 來源拆分）落地欄位
FUNNEL_FIELDS = [
    "shop_uv", "hybrid_uv",
    "placed_buyers", "paid_buyers", "confirmed_buyers",
    "placed_sales", "paid_sales", "confirmed_sales",
    "confirmed_sales_per_buyer",
]
SOURCE_FIELDS = ["total_sales", "product_card", "live", "video", "affiliate", "paid_ads"]


@dataclass
class DayData:
    shop: str
    dt: date
    products: list[dict] = field(default_factory=list)   # 商品層列
    models: list[dict] = field(default_factory=list)     # 規格層列
    shop_daily: dict = field(default_factory=dict)       # 大盤一列
    raw: dict = field(default_factory=dict)              # 原始 JSON 快照


def _day_range_epoch(day: date) -> tuple[int, int]:
    start = int(datetime(day.year, day.month, day.day).timestamp())
    return start, start + 86399


def _base_params(day: date) -> dict:
    start, end = _day_range_epoch(day)
    return {"period": "yesterday", "start_time": str(start), "end_time": str(end)}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def collect_day(client: ShopeeDataClient, shop: str, day: date, throttle: float = 1.0) -> DayData:
    """抓 day 當天三張表。throttle = 每個 API call 間隔秒數（禮貌抓取）。"""
    data = DayData(shop=shop, dt=day)
    base = _base_params(day)

    # 1) 商品明細（分頁抓全店，models inline）
    page = 1
    items: list[dict] = []
    while True:
        result = client.get("/api/mydata/v4/product/performance/", {
            **base,
            "keyword": "", "category_type": "shopee", "category_id": "-1",
            "page_size": str(PAGE_SIZE), "page_num": str(page),
            "order_type": "confirmed", "order_by": "confirmed_sales.desc",
        })
        batch = result.get("items") or []
        items.extend(batch)
        total = result.get("total", 0)
        logger.info(f"[{shop}] {day} 商品明細 第{page}頁 {len(batch)} 筆（累計 {len(items)}/{total}）")
        if len(items) >= total or not batch:
            break
        page += 1
        time.sleep(throttle)

    for it in items:
        row = {f: it.get(f) for f in PRODUCT_FIELDS}
        data.products.append(row)
        for m in it.get("models") or []:
            mrow = {"product_id": it.get("id")}
            mrow.update({f: m.get(f) for f in MODEL_FIELDS})
            data.models.append(mrow)
    data.raw["product_performance"] = items

    # 2) 每日大盤 funnel
    time.sleep(throttle)
    funnel = client.get("/api/mydata/v3/sales/overview/funnel/", dict(base))
    data.raw["sales_funnel"] = funnel

    # 3) 來源拆分 + 關鍵指標
    time.sleep(throttle)
    sources = client.get("/api/mydata/v1/dashboard/traffic-sources/", {
        **base, "order_type": "confirmed", "need_paid_ads_data": "true",
    })
    data.raw["traffic_sources"] = sources
    time.sleep(throttle)
    metrics = client.get("/api/mydata/v3/dashboard/key-metrics/", {**base, "fetag": "fetag"})
    data.raw["key_metrics"] = metrics

    # 大盤壓成一列
    row: dict = {}
    for f in FUNNEL_FIELDS:
        node = funnel.get(f)
        row[f] = _num(node.get("value")) if isinstance(node, dict) else _num(node)
    overview = sources.get("overview") or {}
    for f in SOURCE_FIELDS:
        row[f"src_{f}"] = _num(overview.get(f))
        row[f"src_{f}_ratio"] = _num(overview.get(f + "_ratio"))
    pv = metrics.get("shop_pv")
    row["shop_pv"] = _num(pv.get("value")) if isinstance(pv, dict) else _num(pv)
    data.shop_daily = row

    logger.info(f"[{shop}] {day} 完成：商品 {len(data.products)} 筆 / 規格 {len(data.models)} 筆 / 大盤 1 列")
    return data


def save_raw_snapshot(data: DayData, root: str | Path) -> Path:
    """原封存檔快照：data/shopee_analytics/raw/{shop}/{YYYY-MM-DD}/*.json"""
    day_dir = Path(root) / "raw" / data.shop / data.dt.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in data.raw.items():
        (day_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    logger.info(f"raw 快照已存 {day_dir}")
    return day_dir


def yesterday() -> date:
    return date.today() - timedelta(days=1)
