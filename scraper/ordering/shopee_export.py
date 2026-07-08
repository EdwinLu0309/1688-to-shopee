"""讀取蝦皮訂單匯出（Order.toship.*.xlsx）→ OrderLine 清單。

蝦皮「待出貨」匯出檔通常有密碼（msoffcrypto 解），內容是**整店**所有待出貨訂單，
一張訂單的每個 SKU 各一列。欄位位置（0-index，2026-07 實測）：
  0 訂單編號 / 5 買家帳號 / 25 商品名稱 / 27 商品選項名稱 /
  32 主商品貨號 / 33 商品選項貨號 / 34 數量
下游用「商品選項貨號」去 join 訂貨主檔，只有主檔裡有的（＝預購品）才需要 1688 下單。
"""

from __future__ import annotations

import io
from pathlib import Path

import msoffcrypto
from loguru import logger
from python_calamine import CalamineWorkbook

from .models import OrderLine

# 匯出檔欄位索引（0-index）
COL_ORDER_NO = 0      # 訂單編號
COL_BUYER = 5         # 買家帳號
COL_PRODUCT_NAME = 25 # 商品名稱
COL_OPTION_NAME = 27  # 商品選項名稱
COL_SKU_CODE = 33     # 商品選項貨號（join key）
COL_QTY = 34          # 數量

# 表頭關鍵字（用來確認欄位沒跑位；蝦皮偶爾改版）
_HEADER_CHECK = {
    COL_ORDER_NO: "訂單編號",
    COL_BUYER: "買家帳號",
    COL_SKU_CODE: "商品選項貨號",
    COL_QTY: "數量",
}


def _decrypt_to_bytes(path: Path, password: str | None) -> bytes:
    """回傳可被 calamine 讀的 xlsx bytes。加密檔用密碼解、未加密檔原樣回傳。"""
    with open(path, "rb") as f:
        raw = f.read()
    office = msoffcrypto.OfficeFile(io.BytesIO(raw))
    if not office.is_encrypted():
        logger.debug(f"{path.name} 未加密，直接讀取")
        return raw
    if not password:
        raise ValueError(f"{path.name} 有密碼保護，請提供密碼")
    out = io.BytesIO()
    office.load_key(password=password)
    office.decrypt(out)
    logger.debug(f"{path.name} 已用密碼解密")
    return out.getvalue()


def _verify_header(header: list) -> None:
    """確認關鍵欄位表頭沒跑位，跑位就 raise（避免默默抓錯欄）。"""
    for idx, expect in _HEADER_CHECK.items():
        got = str(header[idx]).strip() if idx < len(header) else ""
        if expect not in got:
            raise ValueError(
                f"蝦皮匯出欄位跑位：第 {idx} 欄預期含「{expect}」，實際「{got}」。"
                f"蝦皮可能改版，請檢查 shopee_export.py 的欄位索引。"
            )


def read_order_lines(path: str | Path, password: str | None = None) -> list[OrderLine]:
    """讀蝦皮匯出檔 → OrderLine 清單（一列一個 SKU）。

    - 自動判斷是否加密；加密則用 password 解。
    - 校驗表頭關鍵欄位位置。
    - 跳過空貨號/數量非正整數的列。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"匯出檔不存在：{path}")

    data = _decrypt_to_bytes(path, password)
    wb = CalamineWorkbook.from_filelike(io.BytesIO(data))
    sheet_name = wb.sheet_names[0]
    rows = wb.get_sheet_by_name(sheet_name).to_python()
    if not rows:
        logger.warning(f"{path.name} 沒有資料列")
        return []

    _verify_header(rows[0])

    lines: list[OrderLine] = []
    skipped = 0
    for row in rows[1:]:
        sku = _cell(row, COL_SKU_CODE)
        qty_raw = _cell(row, COL_QTY)
        if not sku:
            skipped += 1
            continue
        try:
            qty = int(float(qty_raw))
        except (TypeError, ValueError):
            logger.debug(f"數量無法解析，跳過：訂單 {_cell(row, COL_ORDER_NO)} 貨號 {sku} 數量={qty_raw!r}")
            skipped += 1
            continue
        if qty <= 0:
            skipped += 1
            continue
        lines.append(
            OrderLine(
                order_no=_cell(row, COL_ORDER_NO),
                buyer=_cell(row, COL_BUYER),
                product_name=_cell(row, COL_PRODUCT_NAME),
                option_name=_cell(row, COL_OPTION_NAME),
                sku_code=sku,
                quantity=qty,
            )
        )

    logger.info(f"{path.name}：讀到 {len(lines)} 個訂單明細列（跳過 {skipped} 列）")
    return lines


def _cell(row: list, idx: int) -> str:
    """取欄位並轉成 strip 過的字串（None → 空字串）。"""
    if idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    return str(v).strip()
