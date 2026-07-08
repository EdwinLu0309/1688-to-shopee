"""訂貨系統資料模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OrderLine:
    """蝦皮訂單匯出的一列（一張訂單裡的一個 SKU）。

    對應 Order.toship.*.xlsx 欄位（0-index）：
    0 訂單編號 / 5 買家帳號 / 25 商品名稱 / 27 商品選項名稱 /
    32 主商品貨號 / 33 商品選項貨號 / 34 數量
    """

    order_no: str          # 訂單編號（col 0）
    buyer: str             # 買家帳號（col 5）
    product_name: str      # 商品名稱（col 25）
    option_name: str       # 商品選項名稱（col 27）
    sku_code: str          # 商品選項貨號（col 33）＝ join key
    quantity: int          # 數量（col 34）


@dataclass
class MasterEntry:
    """訂貨主檔（分頁1）的一列：商品選項貨號 → 1688 下單所需資訊。"""

    sku_code: str          # 商品選項貨號（join key）
    code: str              # 編號（如 P14AE1）
    short_name: str        # 商品簡稱
    url_1688: str          # 1688 網址
    spec1: str             # 規格一(1688原色)，餵 cart_adder 選色
    spec2: str             # 規格二(1688尺碼)，餵 cart_adder 選尺碼
    cost_cny: float | None # 進貨單價¥（可能未填）


@dataclass
class SummaryRow:
    """每日訂購彙總（分頁2）的一列：某日某 SKU 的訂貨總量與成本。"""

    date: str              # 日期（YYYY-MM-DD，＝匯入/下單日）
    sku_code: str          # 商品選項貨號
    code: str              # 編號
    short_name: str        # 商品簡稱
    spec1: str             # 規格一
    spec2: str             # 規格二
    total_qty: int         # 總數量（該日該 SKU 加總）
    cost_cny: float | None # 進貨¥（來自主檔）
    subtotal_cny: float | None  # 成本小計＝總數量 × 進貨¥（進貨¥ 缺則 None）
    order_status: str = ""      # 下單狀態（cart_adder 回寫）
    order_time: str = ""        # 下單時間
