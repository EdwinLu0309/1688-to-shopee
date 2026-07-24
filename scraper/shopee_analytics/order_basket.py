"""訂單商品聯動（basket）分析（#S101）。

蝦皮訂單銷售報表（Order.all，msoffcrypto 加密、密碼=帳號手機末 6 碼）拆解
「買 A 配 B」共現組合 + 「買它常一次買幾件」數量分布。⚠️含買家個資（地址/電話/姓名），
**只取訂單編號/買家/商品/貨號/數量/日期/狀態，不碰個資欄、不落地個資**。

訂單報表下載需密碼 + 觸發下載時簡訊驗證（個資法）——非廣告那種免驗證匯出，
故走「Edwin 手動匯出 → 本工具讀已下載檔」的半自動（basket 是慢變數，不需每天自動）。
落地累積「訂單明細」分頁（去個資）→ basket 從累積明細算，越多天越準。
"""

from __future__ import annotations

import io
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from loguru import logger

# 訂單報表欄位（Order.all 表頭，2026-07 實測；非個資欄才取）
COL_ORDER = 0        # 訂單編號
COL_STATUS = 1       # 訂單狀態
COL_BUYER = 5        # 買家帳號
COL_DATE = 6         # 訂單成立日期
COL_NAME = 25        # 商品名稱
COL_PID = 26         # 商品ID
COL_OPTION = 27      # 商品選項名稱
COL_SKU = 33         # 商品選項貨號
COL_QTY = 34         # 數量

# 排除的訂單狀態（不成立不算真實購買）
EXCLUDE_STATUS_KW = ("不成立",)


@dataclass
class OrderDetail:
    order_id: str
    buyer: str
    date: str
    status: str
    pid: str
    name: str
    sku: str
    qty: int


@dataclass
class BasketResult:
    details: list[OrderDetail] = field(default_factory=list)
    n_orders: int = 0
    n_products: int = 0
    pairs: list[tuple[str, str, int]] = field(default_factory=list)      # (nameA, nameB, 共現單數)
    multibuy: list[tuple[str, float, int, int]] = field(default_factory=list)  # (name, 均量, 單數, 最多)
    status_counts: dict = field(default_factory=dict)


def read_order_details(path: str | Path, password: str | None = None) -> list[OrderDetail]:
    """解密讀訂單報表 → OrderDetail（只取非個資欄；排除不成立訂單）。"""
    import msoffcrypto
    from python_calamine import CalamineWorkbook

    raw = Path(path).read_bytes()
    try:
        office = msoffcrypto.OfficeFile(io.BytesIO(raw))
        out = io.BytesIO()
        office.load_key(password=password or "")
        office.decrypt(out)
        data = out.getvalue()
    except Exception as e:
        if password:
            raise ValueError(f"訂單報表解密失敗（密碼錯誤？）：{e}") from e
        data = raw  # 未加密

    rows = CalamineWorkbook.from_filelike(io.BytesIO(data)).get_sheet_by_index(0).to_python()
    out_rows: list[OrderDetail] = []
    for r in rows[1:]:
        if not r or not r[COL_ORDER]:
            continue
        status = str(r[COL_STATUS])
        if any(kw in status for kw in EXCLUDE_STATUS_KW):
            continue
        try:
            qty = int(float(r[COL_QTY]))
        except (ValueError, TypeError):
            qty = 1
        out_rows.append(OrderDetail(
            order_id=str(r[COL_ORDER]), buyer=str(r[COL_BUYER]),
            date=str(r[COL_DATE])[:10], status=status,
            pid=str(r[COL_PID]), name=str(r[COL_NAME]), sku=str(r[COL_SKU]), qty=qty,
        ))
    return out_rows


def analyze(details: list[OrderDetail], top: int = 20, min_orders: int = 3) -> BasketResult:
    """從訂單明細算商品共現 pairs + 多件購買分布（用商品ID 聚合到商品層）。"""
    order_items: dict[str, list[str]] = defaultdict(list)
    qty_by_prod: dict[str, list[int]] = defaultdict(list)
    name_of: dict[str, str] = {}
    status_c: Counter = Counter()
    for d in details:
        order_items[d.order_id].append(d.pid)
        qty_by_prod[d.pid].append(d.qty)
        name_of[d.pid] = d.name
        status_c[d.status] += 1

    pair_c: Counter = Counter()
    for items in order_items.values():
        for a, b in combinations(sorted(set(items)), 2):
            pair_c[(a, b)] += 1
    pairs = [(name_of[a], name_of[b], n) for (a, b), n in pair_c.most_common(top)]

    multi = [
        (name_of[pid], sum(q) / len(q), len(q), max(q))
        for pid, q in qty_by_prod.items() if len(q) >= min_orders
    ]
    multi.sort(key=lambda x: -x[1])

    return BasketResult(
        details=details, n_orders=len(order_items), n_products=len(name_of),
        pairs=pairs, multibuy=multi[:top], status_counts=dict(status_c),
    )


def save_to_sheet(res: BasketResult, sheet_id: str, shop: str = "nail") -> None:
    """落地 Sheet：① 訂單明細_累積（去個資，去重 append）② 商品聯動摘要（覆寫）。"""
    from .storage_sheet import _get_client

    sh = _get_client().open_by_key(sheet_id)

    # ① 訂單明細（去個資，累積；主鍵 訂單編號+貨號 去重）
    detail_hdr = ["訂單日期", "賣場", "訂單編號", "買家帳號", "商品ID", "商品名稱", "商品選項貨號", "數量", "訂單狀態"]
    try:
        ws = sh.worksheet("訂單明細_累積")
    except Exception:
        ws = sh.add_worksheet(title="訂單明細_累積", rows=20000, cols=len(detail_hdr) + 1)
        ws.append_row(detail_hdr, value_input_option="RAW")
    existing = {(r[2], r[6]) for r in ws.get_values("A:G")[1:] if len(r) >= 7}  # (訂單編號, 貨號)
    new_rows = [
        [d.date, shop, d.order_id, d.buyer, d.pid, d.name, d.sku, d.qty, d.status]
        for d in res.details if (d.order_id, d.sku) not in existing
    ]
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
    logger.info(f"訂單明細_累積：新增 {len(new_rows)} 列（去重後）")

    # ② 商品聯動摘要：從「累積所有月份」重算（每月帶入一份，樣本越多越準）
    all_rows = ws.get_values("A:I")[1:]  # 含剛 append 的全部歷史
    acc = [
        OrderDetail(order_id=r[2], buyer="", date=r[0],
                    status=r[8] if len(r) > 8 else "", pid=r[4], name=r[5], sku=r[6],
                    qty=int(float(r[7])) if len(r) > 7 and r[7] else 1)
        for r in all_rows if len(r) >= 8 and r[2]
    ]
    acc_res = analyze(acc)
    dates = [r[0] for r in all_rows if r and r[0]]
    span = f"{min(dates)} ~ {max(dates)}" if dates else "—"

    try:
        ws2 = sh.worksheet("商品聯動摘要")
        ws2.clear()
    except Exception:
        ws2 = sh.add_worksheet(title="商品聯動摘要", rows=200, cols=6)
    block = [[f"涵蓋期間 {span}｜{acc_res.n_orders} 張訂單／{acc_res.n_products} 品項", "", ""]]
    block += [["【買 A 配 B — 最常一起買】", "", ""], ["商品 A", "商品 B", "共買訂單數"]]
    block += [[a, b, n] for a, b, n in acc_res.pairs]
    block += [["", "", ""], ["【常一次買多件】", "", ""], ["商品", "平均件數", "最多/訂單數"]]
    block += [[name, round(avg, 1), f"{mx}/{cnt}"] for name, avg, cnt, mx in acc_res.multibuy]
    ws2.update(values=block, range_name="A1", raw=True)
    logger.info(f"商品聯動摘要（累積 {span}）：pairs {len(acc_res.pairs)} + 多件 {len(acc_res.multibuy)}")


def format_report(res: BasketResult) -> str:
    lines = [
        f"訂單 {res.n_orders} 張／商品品項 {res.n_products}／狀態 {res.status_counts}",
        "\n【買 A 配 B — 最常一起買的組合】",
    ]
    for a, b, n in res.pairs[:10]:
        lines.append(f"  {n} 單：{a[:26]} ＋ {b[:26]}")
    lines.append("\n【常一次買多件的商品（平均購買量）】")
    for name, avg, cnt, mx in res.multibuy[:10]:
        lines.append(f"  平均 {avg:.1f} 件/單（最多 {mx}）×{cnt} 單  {name[:30]}")
    return "\n".join(lines)
