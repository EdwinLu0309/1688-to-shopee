"""抓 Kkren（巧巧郎/jyb）「已出貨」集運訂單 → Kkren_Data 7 欄（給到貨核對）。

去風險定案（#S085）：Kkren 是 SPA，認證＝localStorage 的 accessToken（Bearer）。
Edwin 用 kkren_probe 登入一次存完整登入態 `config/kkren_state.json`（含 token），
之後用 httpx 帶 Bearer 直接打 REST API，無頭自動、免再登（token 過期才重登）。

- 已出貨端點：`GET api.jyb.com.tw/jyo/v1frontend/jyorder/index`
  `?page=&pageSize=&createdStart=&createdEnd=&jyoPayStatus=9&jyoStatus=5`
  （jyoPayStatus=9 已付款、jyoStatus=5 已出貨）
- 一訂單多包裹 → 一列一個 `parcels[].trackingNo`（物流單號，對 1688_DB!AF 運單號）。
- 到貨日自帶：`jyoExtraInfo.schedule.calJycutAt`(結單) / `calDelivAt`(到貨)。
- 重量：`parcels[].weight ÷1000`（實測：1980→1.98kg）。

Kkren_Data 7 欄：訂單編號 | 下單日期 | 結單日 | 預計到貨時間 | 物流單號 | 重量(KG) | 物流狀態
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import httpx
from loguru import logger

from config import settings

API = "https://api.jyb.com.tw"
STATE_PATH = settings.BASE_DIR / "config" / "kkren_state.json"

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
_WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"]  # date.weekday() 0=Mon

KKREN_HEADERS = ["訂單編號", "下單日期", "結單日", "預計到貨時間", "物流單號", "重量(KG)", "物流狀態"]


class KkrenAuthError(RuntimeError):
    """token 失效／未登入。請重跑 Kkren 登入（kkren_probe）。"""


@dataclass
class KkrenParcel:
    order_no: str = ""       # 訂單編號 oid
    order_date: str = ""     # 下單日期
    cut_wday: str = ""       # 結單日（星期X結單）
    eta_wday: str = ""       # 預計到貨（星期X）
    tracking_no: str = ""    # 物流單號 ← 對 1688 運單號
    weight_kg: float = 0.0   # 重量(KG)
    status: str = ""         # 物流狀態

    def to_row(self) -> list:
        return [self.order_no, self.order_date, self.cut_wday, self.eta_wday,
                self.tracking_no, self.weight_kg, self.status]


def load_token(state_path: Path | str = STATE_PATH) -> str:
    p = Path(state_path)
    if not p.exists():
        raise KkrenAuthError(f"找不到 {p}，請先登入 Kkren（跑 kkren_probe）")
    state = json.loads(p.read_text(encoding="utf-8"))
    for origin in state.get("origins", []):
        for kv in origin.get("localStorage", []):
            if kv.get("name") == "accessToken" and kv.get("value"):
                return kv["value"]
    raise KkrenAuthError("kkren_state.json 內找不到 accessToken，請重新登入 Kkren")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json",
            "User-Agent": _UA, "Referer": "https://www.kkren.com.tw/"}


def _wday(dt_str: str) -> str:
    """'2026-07-13 15:00:00' → '一'（週一）。"""
    try:
        d = _dt.datetime.strptime(dt_str[:10], "%Y-%m-%d")
        return _WEEKDAY[d.weekday()]
    except (ValueError, TypeError):
        return ""


def _yuan_g_to_kg(g) -> float:
    try:
        return round(float(g) / 1000.0, 2)
    except (TypeError, ValueError):
        return 0.0


def fetch_shipped_orders(
    token: str,
    created_start: str,
    created_end: str,
    page_size: int = 50,
    max_pages: int = 40,
    callback: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """抓 [created_start, created_end] 區間所有「已出貨」訂單（翻頁抓完）。"""
    def notify(m):
        logger.info(m)
        if callback:
            try:
                callback(m)
            except Exception:
                pass

    orders: list[dict] = []
    with httpx.Client(headers=_headers(token), timeout=30) as cli:
        for pg in range(1, max_pages + 1):
            url = (f"{API}/jyo/v1frontend/jyorder/index?page={pg}&pageSize={page_size}"
                   f"&createdStart={created_start}&createdEnd={created_end}"
                   f"&jyoPayStatus=9&jyoStatus=5")
            r = cli.get(url)
            if r.status_code == 401:
                raise KkrenAuthError("Kkren token 失效（401），請重新登入 Kkren")
            r.raise_for_status()
            body = r.json()
            lst = body.get("list") or []
            orders.extend(lst)
            total = body.get("listInfo", {}).get("count")
            notify(f"已抓第 {pg} 頁：{len(lst)} 筆（累計 {len(orders)}／共 {total}）")
            if len(lst) < page_size:
                break
    return orders


def to_parcels(orders: list[dict]) -> list[KkrenParcel]:
    """訂單 list → 一列一包裹（KkrenParcel）。"""
    out: list[KkrenParcel] = []
    for o in orders:
        order_no = str(o.get("oid") or "")
        order_date = str(o.get("createdAt") or "")[:10]
        sched = (o.get("jyoExtraInfo") or {}).get("schedule") or {}
        cut = _wday(str(sched.get("calJycutAt") or ""))
        eta = _wday(str(sched.get("calDelivAt") or ""))
        for p in (o.get("parcels") or []):
            tno = str(p.get("trackingNo") or "").strip()
            if not tno:
                continue
            status = " ".join(x for x in [str(p.get("statusAt") or "").strip(),
                                          str(p.get("statusBrief") or p.get("statusName") or "").strip()] if x)
            out.append(KkrenParcel(
                order_no=order_no,
                order_date=order_date,
                cut_wday=(f"星期{cut}結單" if cut else ""),
                eta_wday=(f"星期{eta}" if eta else ""),
                tracking_no=tno,
                weight_kg=_yuan_g_to_kg(p.get("weight")),
                status=status,
            ))
    return out


def scrape_shipped(
    since_days: int = 30,
    created_start: Optional[str] = None,
    created_end: Optional[str] = None,
    state_path: Path | str = STATE_PATH,
    callback: Optional[Callable[[str], None]] = None,
) -> list[KkrenParcel]:
    """抓近 since_days 天的已出貨包裹（或指定日期區間）。"""
    today = _dt.date.today()
    created_end = created_end or today.isoformat()
    created_start = created_start or (today - _dt.timedelta(days=since_days)).isoformat()
    token = load_token(state_path)
    orders = fetch_shipped_orders(token, created_start, created_end, callback=callback)
    parcels = to_parcels(orders)
    logger.info(f"Kkren 已出貨：{len(orders)} 訂單 → {len(parcels)} 包裹（物流單號）")
    return parcels
