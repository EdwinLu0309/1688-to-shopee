"""自動選品廣告（GMV MAX / 全賣場推廣）逐商品明細抓取（#S100）。

自動選品是蝦皮演算法黑箱：你設一個目標 ROAS，它自動全店選品投放。
UI 只顯示活動層一列，但「匯出數據 → 自動選品廣告詳情數據」拆得出逐商品——
而匯出背後是一組 export_job API（trigger→poll→download 回 CSV 全文），可全自動。

佔比重要：自動選品常吃掉整體廣告 ~3 成金額（實測 nail 3,680/13,128），
不拆解＝半盲飛。逐商品成效讓 Edwin 挑「自動試出的高 ROAS 商品 → 轉手動加碼」。

流程（#S100 攔真實匯出得出）：
1. POST export_job/trigger/ {language, report_type:"product_gms__homepage", start_time, end_time} → export_id
2. POST export_job/get_single_result/ {export_id} 輪詢 status=success
3. POST export_job/download/ {export_id} → {file_name, content=CSV 全文}
"""

from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime

from loguru import logger

from .client import ShopeeDataClient

REPORT_TYPE = "product_gms__homepage"

# CSV 欄位（第 8 列表頭）→ 落地欄位。金額欄 CSV 已是「元」，不用再換算。
CSV_COLS = {
    "商品名稱": "name", "商品 ID": "product_id",
    "瀏覽數": "impression", "點擊數": "click", "點擊率": "ctr",
    "轉換數": "conversions", "轉換率": "cr",
    "每一筆轉換的成本": "cost_per_conv",
    "銷售數": "units", "銷售金額": "gmv", "花費": "cost",
    "投入產出比": "roas", "成本收入比率": "cir",
    "優惠券金額": "voucher_amount", "優惠券帶來的銷售額": "voucher_sales",
}
GMS_FIELDS = ["product_id", "name", "impression", "click", "ctr", "conversions",
              "cr", "units", "gmv", "cost", "roas", "cost_per_conv", "cir",
              "voucher_amount", "voucher_sales"]


def _day_epoch(day: date) -> tuple[int, int]:
    start = int(datetime(day.year, day.month, day.day).timestamp())
    return start, start + 86399


def _num(v: str):
    if v in (None, "", "-"):
        return None
    v = v.strip().replace("%", "").replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def collect_gms_detail(client: ShopeeDataClient, day: date,
                       poll_max: int = 40, poll_interval: float = 3.0) -> list[dict]:
    """抓 day 當天自動選品逐商品明細。回逐商品列（排除聚合 Shop GMV Max 列）。"""
    start, end = _day_epoch(day)
    r = client.post("/api/pas/v1/report/export_job/trigger/", {
        "language": "zh-Hant", "report_type": REPORT_TYPE,
        "start_time": start, "end_time": end,
    })
    export_id = r.get("export_id") or r.get("id")
    if not export_id:
        logger.warning(f"自動選品明細 trigger 沒回 export_id：{r}")
        return []

    for i in range(poll_max):
        s = client.post("/api/pas/v1/report/export_job/get_single_result/", {"export_id": export_id})
        if s.get("status") == "success":
            break
        if s.get("status") == "fail":
            logger.warning(f"自動選品明細匯出失敗：{s}")
            return []
        time.sleep(poll_interval)
    else:
        logger.warning(f"自動選品明細匯出逾時（export_id={export_id}）")
        return []

    d = client.post("/api/pas/v1/report/export_job/download/", {"export_id": export_id})
    content = d.get("content", "")
    return _parse_csv(content)


def _parse_csv(content: str) -> list[dict]:
    """解析 GMV MAX detail CSV：前 7 列 metadata、第 8 列表頭、第 9 列起資料
    （首筆是 Shop GMV Max 聚合列，product_id='-'，排除）。"""
    rows = list(csv.reader(io.StringIO(content)))
    header_idx = next((i for i, r in enumerate(rows) if "商品 ID" in r), None)
    if header_idx is None:
        logger.warning("自動選品 CSV 找不到表頭列")
        return []
    hdr = rows[header_idx]
    idx = {CSV_COLS[h]: hdr.index(h) for h in CSV_COLS if h in hdr}
    out: list[dict] = []
    for r in rows[header_idx + 1:]:
        if len(r) <= idx.get("product_id", 99):
            continue
        pid = r[idx["product_id"]].strip()
        if pid in ("", "-"):  # 聚合列 Shop GMV Max
            continue
        row = {"product_id": pid, "name": r[idx["name"]]}
        for f in GMS_FIELDS:
            if f in ("product_id", "name") or f not in idx:
                continue
            row[f] = _num(r[idx[f]])
        out.append(row)
    return out
