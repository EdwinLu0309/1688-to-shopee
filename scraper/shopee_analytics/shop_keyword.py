"""賣場廣告逐關鍵字明細抓取（#S100）。

手動賣場廣告每天燒 $2,000-3,000，是廣告重點。UI 詳情頁「匯出數據」拆得出
逐關鍵字（投放關鍵字 × 搜尋詞 × 比對模式）成效——哪些搜尋詞帶轉換、哪些燒錢。
走 export_job flow：report_type=shop_manual__single_detail、extra_body 帶 campaign_id。

一個賣場廣告一天可展開數千筆搜尋詞（廣泛比對）→ **只落地當天有花費或轉換的**
（實測 2722 → 330 筆），避免每天塞爆。多個賣場廣告各 loop 一次。
"""

from __future__ import annotations

import csv
import io
import time
from datetime import date

from loguru import logger

from .client import ShopeeDataClient
from .gms_detail import _num, run_export_job

REPORT_TYPE = "shop_manual__single_detail"

CSV_COLS = {
    "關鍵字": "keyword", "比對模式": "match_type", "搜尋關鍵字": "search_term",
    "瀏覽數": "impression", "點擊數": "click", "點擊率": "ctr",
    "轉換數": "conversions", "轉換率": "cr",
    "銷售數": "units", "銷售金額": "gmv", "花費": "cost", "投入產出比": "roas",
}
KW_FIELDS = ["campaign_id", "campaign_name", "keyword", "match_type", "search_term",
             "impression", "click", "ctr", "conversions", "cr", "units", "gmv", "cost", "roas"]


def collect_shop_keyword_detail(client: ShopeeDataClient, day: date,
                                campaigns: list[tuple[int, str]]) -> list[dict]:
    """抓 day 當天各手動賣場廣告的逐關鍵字明細（只留有花費/轉換的）。

    campaigns = [(campaign_id, 活動名), ...]，通常從當天廣告日報篩 type=shop_manual 得來。
    """
    out: list[dict] = []
    for i, (cid, name) in enumerate(campaigns):
        if i:
            time.sleep(8)  # export job 間隔，避讓「too many export requests」限流
        content = run_export_job(client, REPORT_TYPE, day, extra_body={"campaign_id": cid})
        if not content:
            continue
        rows = _parse_csv(content, cid, name)
        out.extend(rows)
        logger.info(f"賣場廣告「{name}」逐關鍵字 {len(rows)} 筆（有花費/轉換）")
    return out


def _parse_csv(content: str, campaign_id: int, campaign_name: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(content)))
    header_idx = next((i for i, r in enumerate(rows) if "關鍵字" in r and "花費" in r), None)
    if header_idx is None:
        return []
    hdr = rows[header_idx]
    idx = {CSV_COLS[h]: hdr.index(h) for h in CSV_COLS if h in hdr}
    out: list[dict] = []
    for r in rows[header_idx + 1:]:
        if len(r) <= max(idx.values(), default=0):
            continue
        cost = _num(r[idx["cost"]]) or 0
        conv = _num(r[idx["conversions"]]) or 0
        if cost <= 0 and conv <= 0:  # 只留有意義的（廣泛比對展開幾千筆搜尋詞，多數空）
            continue
        row = {"campaign_id": campaign_id, "campaign_name": campaign_name}
        for f, col in idx.items():
            row[f] = r[col] if f in ("keyword", "match_type", "search_term") else _num(r[col])
        out.append(row)
    return out
