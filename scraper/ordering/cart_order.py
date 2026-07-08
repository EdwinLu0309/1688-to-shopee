"""下單驅動：每日彙總 → 1688 加購物車（CartAdder）→ 回寫狀態；核對（CartVerifier）。

彙總（分頁2）只有貨號+規格+總量，沒有 1688 網址 → 這裡 join 訂貨主檔補 url，
再建成 cart_adder 吃的 OrderItem，按 url 分組加購（同商品多規格一次加）。

⚠️ 規格二尺碼格式（如「S（80~95斤）」）是否與 1688 頁面尺碼列逐字相同＝首次實跑驗證點；
若對不上，cart_adder 會回「❌ 規格不符」，看回寫狀態即知。
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from config import settings

from .cart_adder import CartAdder
from .cart_verifier import CartVerifier
from .models import MasterEntry, OrderItem, SummaryRow
from .order_sheet import OrderSheet

DEFAULT_COOKIE_PATH = str(settings.COOKIE_PATH)  # config/cookies.json（1688 登入 cookie）


def build_order_items(
    summary_rows: list[SummaryRow],
    master: dict[str, MasterEntry],
) -> tuple[list[OrderItem], list[str]]:
    """把彙總列 join 主檔 → OrderItem 清單。回傳 (items, 缺網址的貨號)。

    row_index 用 enumerate 索引（回寫時對回 sku_code）。
    """
    items: list[OrderItem] = []
    missing_url: list[str] = []
    for i, s in enumerate(summary_rows):
        m = master.get(s.sku_code)
        url = m.url_1688 if m else ""
        if not url:
            missing_url.append(s.sku_code)
            continue
        items.append(OrderItem(
            row_index=i,
            product_code=s.code,
            quantity=s.total_qty,
            spec1=s.spec1,
            spec2=s.spec2,
            url_1688=url,
            sku_name=s.short_name,
            sku_code=s.sku_code,
        ))
    return items, missing_url


async def place_orders(
    items: list[OrderItem],
    cookie_path: str = DEFAULT_COOKIE_PATH,
    headless: bool = False,
    callback: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> dict[int, str]:
    """驅動 CartAdder，按 url 分組加購。回傳 {row_index: status}。

    cookie 失效 / 驗證碼超時會在 status 反映（整組），不會 raise 出來。
    """
    def _notify(msg: str) -> None:
        logger.info(msg)
        if callback:
            try:
                callback(msg)
            except Exception:
                pass

    statuses: dict[int, str] = {}
    adder = CartAdder(cookie_path, headless=headless, callback=callback)
    try:
        await adder.start()
    except (FileNotFoundError, ValueError) as e:
        _notify(f"❌ Cookie 問題：{e}（請先用 GUI 的「🔑 登入 1688」匯出 cookie）")
        return {it.row_index: "❌ 頁面錯誤" for it in items}

    # 按 url 分組（同商品頁多規格一次加購）
    groups: dict[str, list[OrderItem]] = {}
    for it in items:
        groups.setdefault(it.url_1688, []).append(it)
    _notify(f"{len(items)} 個 SKU → 整併為 {len(groups)} 個商品頁")

    try:
        for i, (url, group) in enumerate(groups.items(), 1):
            if cancel_event and cancel_event.is_set():
                _notify("已手動停止")
                break
            first = group[0]
            _notify(f"[{i}/{len(groups)}] 編號 {first.product_code} {first.sku_name}（{len(group)} 規格）")
            try:
                group_status = await adder.add_multi_to_cart(group)
            except RuntimeError as e:
                msg = str(e)
                if "CAPTCHA" in msg:
                    _notify("⏸️ 驗證碼等待超時，中斷。手動解完後重跑")
                    for it in group:
                        statuses[it.row_index] = "⏸️ 驗證碼中斷"
                    break
                if "Cookie expired" in msg:
                    _notify("❌ Cookie 已失效，請重新登入 1688")
                    for it in group:
                        statuses[it.row_index] = "❌ 頁面錯誤"
                    break
                group_status = {it.row_index: "❌ 頁面錯誤" for it in group}
            statuses.update(group_status)
            if i < len(groups):
                await asyncio.sleep(random.uniform(3, 8))
    finally:
        await adder.close()

    return statuses


async def verify_cart(
    items: list[OrderItem],
    cookie_path: str = DEFAULT_COOKIE_PATH,
    headless: bool = False,
    callback: Optional[Callable[[str], None]] = None,
) -> dict[int, str]:
    """驅動 CartVerifier 核對購物車。回傳 {row_index: 核對狀態}。"""
    verifier = CartVerifier(cookie_path, headless=headless, callback=callback)
    try:
        await verifier.start()
        cart_products = await verifier.read_cart_products()
        results = verifier.verify(items, cart_products)
    finally:
        await verifier.close()
    return {r.row_index: r.status for r in results}


def run_place_orders(
    date: str,
    cookie_path: str = DEFAULT_COOKIE_PATH,
    headless: bool = False,
    only_unordered: bool = True,
    callback: Optional[Callable[[str], None]] = None,
    sheet: OrderSheet | None = None,
) -> dict[str, str]:
    """高階：讀某日彙總 → 建 OrderItem → 加購 → 回寫分頁2 下單狀態。

    only_unordered=True 只處理「下單狀態」空的列（避免重複下單）。
    回傳 {sku_code: status}。
    """
    from datetime import datetime

    sheet = sheet or OrderSheet()
    master = sheet.load_master()
    summary_rows = _read_summary_rows(sheet, date, only_unordered=only_unordered)
    if not summary_rows:
        logger.warning(f"{date} 沒有待下單的彙總列")
        return {}

    items, missing_url = build_order_items(summary_rows, master)
    if missing_url:
        logger.warning(f"{len(missing_url)} 個貨號在主檔找不到網址，跳過：{missing_url[:5]}")

    statuses = asyncio.run(place_orders(items, cookie_path, headless, callback))

    # row_index → sku_code
    idx_to_sku = {it.row_index: it.sku_code for it in items}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    result: dict[str, str] = {}
    for row_index, status in statuses.items():
        sku = idx_to_sku.get(row_index)
        if not sku:
            continue
        sheet.update_order_status(date, sku, status, now)
        result[sku] = status
    logger.info(f"下單完成，回寫 {len(result)} 筆狀態")
    return result


def _read_summary_rows(sheet: OrderSheet, date: str, only_unordered: bool) -> list[SummaryRow]:
    """從 live 分頁2 讀某日彙總成 SummaryRow（下單用；含既有下單狀態判斷）。"""
    ws = sheet._sh.worksheet(settings.ORDER_SUMMARY_TAB)
    rows = ws.get_all_values()
    out: list[SummaryRow] = []
    for row in rows[1:]:
        if _g(row, 0) != date:
            continue
        status = _g(row, 9)
        if only_unordered and status:  # 已有下單狀態 → 跳過
            continue
        try:
            qty = int(float(_g(row, 6) or 0))
        except ValueError:
            qty = 0
        out.append(SummaryRow(
            date=_g(row, 0), sku_code=_g(row, 1), code=_g(row, 2), short_name=_g(row, 3),
            spec1=_g(row, 4), spec2=_g(row, 5), total_qty=qty,
            cost_cny=None, subtotal_cny=None, order_status=status,
        ))
    return out


def _g(row: list, idx: int) -> str:
    if idx >= len(row):
        return ""
    v = row[idx]
    return str(v).strip() if v is not None else ""
