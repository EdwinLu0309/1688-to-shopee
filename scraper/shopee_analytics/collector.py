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

# 廣告層（CPC 廣告活動，pas homepage query；金額欄 ÷100000）
# broad_=廣義歸因（含間接）、direct_=直接點擊當下。cost/gmv/budget 都是 ÷100000 的「分×1000」。
AD_META_FIELDS = ["campaign_id", "title", "type", "state", "daily_budget", "total_budget"]
AD_REPORT_FIELDS = [
    "cost", "impression", "click", "ctr", "cpc", "cpm",
    "atc", "atc_rate", "checkout", "cr",
    "broad_order", "broad_gmv", "broad_roi", "broad_cir",
    "direct_order", "direct_gmv", "direct_roi", "direct_cir",
    "page_views", "unique_visitors", "avg_rank",
]
# 這些欄位是「金額×1000」(÷100000 得元)：cost/gmv/cpc/cpm/budget
AD_MONEY_FIELDS = {
    "cost", "cpc", "cpm", "broad_gmv", "direct_gmv", "daily_budget", "total_budget",
}
# 廣告要打兩種 campaign_type 才完整（#S100 Edwin 對帳發現總額差 3,680=自動選品）：
# - cpc_homepage_v3 = 「廣告群組與個別廣告」清單（商品手動/自動加碼 + 賣場廣告）
# - product_gms     = 「自動選品廣告（全賣場推廣）」獨立一塊（total=1 的聚合條目）
# 兩者相加 = 廣告頁「所有廣告成效」總花費（實測 9,447.07+3,680.84=13,128 分毫不差）
AD_CAMPAIGN_TYPES = ["cpc_homepage_v3", "product_gms"]

# 大盤日報的廣告合計欄（由 ads 明細加總；跟當天營收同一列看「花多少賺多少」）
AD_TOTAL_FIELDS = ["ad_cost", "ad_gmv", "ad_roi"]


@dataclass
class DayData:
    shop: str
    dt: date
    products: list[dict] = field(default_factory=list)   # 商品層列
    models: list[dict] = field(default_factory=list)     # 規格層列
    shop_daily: dict = field(default_factory=dict)       # 大盤一列
    ads: list[dict] = field(default_factory=list)        # 廣告活動層列
    gms: list[dict] = field(default_factory=list)        # 自動選品逐商品列
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

    # 4) 廣告活動層（pas homepage query，POST 翻頁；只留當天有活動的＝cost>0 或 impression>0）
    time.sleep(throttle)
    data.ads, data.raw["ads_homepage"] = _collect_ads(client, day, throttle)

    # 廣告合計進大盤列（= 廣告頁「所有廣告成效」總卡；含自動選品）
    ad_cost = sum(a.get("cost") or 0 for a in data.ads)
    ad_gmv = sum(a.get("broad_gmv") or 0 for a in data.ads)
    row["ad_cost"] = round(ad_cost, 2)
    row["ad_gmv"] = round(ad_gmv, 2)
    row["ad_roi"] = round(ad_gmv / ad_cost, 2) if ad_cost else None
    data.shop_daily = row

    # 5) 自動選品逐商品明細（export_job trigger→poll→download CSV；黑箱拆解，佔 ~3 成廣告費）
    time.sleep(throttle)
    try:
        from .gms_detail import collect_gms_detail

        data.gms = collect_gms_detail(client, day)
    except Exception as e:  # noqa: BLE001 匯出較慢/易失敗，不擋其他資料
        logger.warning(f"[{shop}] {day} 自動選品明細抓取失敗（不影響其他）：{e}")

    logger.info(
        f"[{shop}] {day} 完成：商品 {len(data.products)} 筆 / 規格 {len(data.models)} 筆 / "
        f"大盤 1 列 / 廣告 {len(data.ads)} 筆 / 自動選品商品 {len(data.gms)} 筆"
    )
    return data


def _collect_ads(client: ShopeeDataClient, day: date, throttle: float) -> tuple[list[dict], list[dict]]:
    """抓 CPC 廣告活動昨日報表。翻頁至 total；落地只留當天有花費/曝光的活動。

    回 (落地列, 原始 entry_list)。
    """
    start, end = _day_range_epoch(day)
    rows: list[dict] = []
    raw_entries: list[dict] = []
    for ctype in AD_CAMPAIGN_TYPES:
        offset, limit, total = 0, 100, None
        while True:
            data = client.post("/api/pas/v1/homepage/query/", {
                "start_time": start, "end_time": end, "offset": offset, "limit": limit,
                "filter": {"campaign_type": ctype},
            })
            entries = data.get("entry_list") or []
            raw_entries.extend(entries)
            if total is None:
                total = data.get("total", len(entries))
            offset += limit
            if offset >= total or not entries:
                break
            time.sleep(throttle)
        time.sleep(throttle)

    for e in raw_entries:
        rep = e.get("report") or {}
        camp = e.get("campaign") or {}
        if not (rep.get("cost") or rep.get("impression")):  # 當天沒跑的活動略過
            continue
        row: dict = {
            "campaign_id": camp.get("campaign_id"),
            "title": e.get("title"), "type": e.get("type"), "state": e.get("state"),
            "daily_budget": camp.get("daily_budget"), "total_budget": camp.get("total_budget"),
        }
        for f in AD_REPORT_FIELDS:
            row[f] = _num(rep.get(f))
        # 金額欄 ÷100000 轉「元」
        for f in AD_MONEY_FIELDS:
            if row.get(f) is not None:
                row[f] = round(row[f] / 100000, 2)
        rows.append(row)
    return rows, raw_entries


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
