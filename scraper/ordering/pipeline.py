"""訂貨 pipeline：蝦皮匯出 → 過濾預購品 → 訂單明細 + 每日彙總 → 今日總金額。

流程：
1. read_order_lines：解密+讀蝦皮匯出 → OrderLine 清單（整店待出貨）
2. load_master：讀訂貨主檔 → 只留「貨號在主檔裡」的（＝預購品，需 1688 下單）
3. build_detail_rows：一列一訂單明細（去重既有）→ 分頁3
4. aggregate_summary：按貨號聚合當日總量 + join 主檔算成本 → 分頁2
5. 回報今日預計總金額

預設 dry-run：只算不寫。--commit 才真的寫 live sheet。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .models import MasterEntry, OrderLine, SummaryRow
from .order_sheet import DEFAULT_SHIP_STATUS, OrderSheet
from .shopee_export import read_order_lines


@dataclass
class ImportResult:
    date: str
    total_lines: int          # 匯出總明細列
    preorder_lines: int       # 命中主檔的明細列（＝預購品）
    unmatched_skus: list[str] # 沒命中主檔的貨號（整店其他商品，正常跳過）
    new_detail_rows: list[list]
    summary_rows: list[SummaryRow]
    total_cost_cny: float
    missing_cost_skus: list[str]  # 命中主檔但主檔沒填進貨¥的貨號

    @property
    def detail_written(self) -> int:
        return len(self.new_detail_rows)


def build_import(
    lines: list[OrderLine],
    master: dict[str, MasterEntry],
    date: str,
    existing_keys: set[tuple[str, str]] | None = None,
) -> ImportResult:
    """純函式：把匯出明細 + 主檔算成明細列 + 彙總（不碰網路）。

    existing_keys：既有明細的 (訂單編號, 貨號)，用來 idempotent 去重。
    """
    existing_keys = existing_keys or set()

    preorder: list[OrderLine] = []
    unmatched: OrderedDict[str, None] = OrderedDict()
    for ln in lines:
        if ln.sku_code in master:
            preorder.append(ln)
        else:
            unmatched.setdefault(ln.sku_code, None)

    # 明細列（去重既有）
    new_detail_rows: list[list] = []
    for ln in preorder:
        key = (ln.order_no, ln.sku_code)
        if key in existing_keys:
            continue
        existing_keys.add(key)  # 同批內也去重
        m = master[ln.sku_code]
        new_detail_rows.append([
            date, ln.order_no, ln.buyer, ln.sku_code, m.code, ln.quantity,
            DEFAULT_SHIP_STATUS, "",
        ])

    # 彙總：按貨號聚合「本次預購品全部」（不只新列——彙總代表當日該 SKU 訂貨總量）
    qty_by_sku: OrderedDict[str, int] = OrderedDict()
    for ln in preorder:
        qty_by_sku[ln.sku_code] = qty_by_sku.get(ln.sku_code, 0) + ln.quantity

    summary_rows: list[SummaryRow] = []
    total_cost = 0.0
    missing_cost: list[str] = []
    for sku, qty in qty_by_sku.items():
        m = master[sku]
        subtotal = None
        if m.cost_cny is not None:
            subtotal = round(m.cost_cny * qty, 2)
            total_cost += subtotal
        else:
            missing_cost.append(sku)
        summary_rows.append(SummaryRow(
            date=date, sku_code=sku, code=m.code, short_name=m.short_name,
            spec1=m.spec1, spec2=m.spec2, total_qty=qty,
            cost_cny=m.cost_cny, subtotal_cny=subtotal,
        ))

    return ImportResult(
        date=date,
        total_lines=len(lines),
        preorder_lines=len(preorder),
        unmatched_skus=list(unmatched.keys()),
        new_detail_rows=new_detail_rows,
        summary_rows=summary_rows,
        total_cost_cny=round(total_cost, 2),
        missing_cost_skus=missing_cost,
    )


def import_orders(
    export_path: str | Path,
    date: str,
    password: str | None = None,
    commit: bool = False,
    sheet: OrderSheet | None = None,
) -> ImportResult:
    """完整匯入流程。commit=False（預設）只算不寫；True 才寫 live sheet。"""
    lines = read_order_lines(export_path, password=password)
    sheet = sheet or OrderSheet()
    master = sheet.load_master()
    existing_keys = sheet.existing_detail_keys() if commit else set()

    result = build_import(lines, master, date, existing_keys=existing_keys)

    if commit:
        sheet.append_details(result.new_detail_rows)
        # 彙總用「該日全部明細」重算，確保跨多次匯入也正確
        sheet.upsert_summary(date, result.summary_rows)
        logger.info(f"已寫入 live sheet：明細 {result.detail_written} 列、彙總 {len(result.summary_rows)} 列")
    else:
        logger.info("dry-run：未寫入 sheet（加 --commit 才寫）")

    return result


def format_report(r: ImportResult, commit: bool) -> str:
    """給 CLI / GUI 顯示的人類可讀摘要。"""
    lines = [
        f"📅 訂貨日期：{r.date}   {'（已寫入 sheet）' if commit else '（dry-run，未寫入）'}",
        f"匯出總明細：{r.total_lines} 列 → 預購品命中：{r.preorder_lines} 列（其餘 {len(r.unmatched_skus)} 個貨號非預購品，跳過）",
        f"新增訂單明細：{r.detail_written} 列 | 彙總 SKU：{len(r.summary_rows)} 個",
        f"💰 今日預計訂貨金額：¥{r.total_cost_cny:,.2f}",
    ]
    if r.missing_cost_skus:
        lines.append(f"⚠️ {len(r.missing_cost_skus)} 個貨號主檔沒填進貨¥（成本未計）：{', '.join(r.missing_cost_skus[:5])}{'…' if len(r.missing_cost_skus) > 5 else ''}")
    if r.summary_rows:
        lines.append("── 彙總明細 ──")
        for s in r.summary_rows:
            cost = f"¥{s.subtotal_cny:,.2f}" if s.subtotal_cny is not None else "（無進貨¥）"
            lines.append(f"  {s.sku_code}  ×{s.total_qty}  {cost}   [{s.spec1} / {s.spec2}]")
    return "\n".join(lines)
