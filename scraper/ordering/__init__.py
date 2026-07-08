"""每日訂貨系統：蝦皮匯出 → 訂單明細/每日彙總 Google Sheet → 1688 下單。

三分頁 Google Sheet（Edwin 的「【Lady】預購商品訂貨表」）：
- 1_訂貨主檔：靜態，商品選項貨號 ↔ 1688 網址/規格對照（隨上架累加，人工/上架流程填）
- 2_每日訂購彙總：由訂單明細自動聚合（訂貨依據，餵 cart_adder）
- 3_訂單明細：一列一張蝦皮訂單明細（出貨依據，按訂單編號）

join key = 商品選項貨號（蝦皮匯出欄33＝編號_顏色（身高款）_尺碼）。
"""

from .models import MasterEntry, OrderLine, SummaryRow

__all__ = ["MasterEntry", "OrderLine", "SummaryRow"]
