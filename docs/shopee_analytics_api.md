# 蝦皮賣家中心「數據中心」API 規格（探勘成果）

> 2026-07-22 於公司 Windows 用 Claude in Chrome 實測驗證（Lady 店 luwei0309）。
> 承 #S097 設計：每日 10:30 抓「前一天」，真相來源 = Google Sheet，SQLite 為加速副本。
> 第一階段鎖定三張表：parentskudetail（商品明細）/ shop-stats（來源拆分）/ sales_overview（每日大盤）。

## 共通規則

- Base URL：`https://seller.shopee.tw`
- 認證：登入後的 cookie（關鍵值 `SPC_CDS`，同時要以 query 參數帶上）
- 共通 query 參數：`SPC_CDS=<cookie值>&SPC_CDS_VER=2`
- 回傳格式：`{"code": 0, "result": {...}}`；`code != 0` 為錯誤（`10006` 參數錯誤；session 過期時參考 1688 經驗攔 `msg`）
- 時間參數：`start_time` / `end_time` 為 epoch 秒（台灣時區當日 00:00:00 ~ 23:59:59）
- `period`：`real_time`（今天）/ `yesterday`（昨天）。**任意歷史日期的 period 值尚未探**（UI 日期選擇器會用別的值，待補探；每日抓昨天的正線用 `yesterday` 已驗證可行）

## 1. 商品明細（= parentskudetail 匯出）

`GET /api/mydata/v4/product/performance/`

| 參數 | 值 | 說明 |
|---|---|---|
| period | `yesterday` | |
| start_time / end_time | epoch | 昨日 00:00:00 / 23:59:59 |
| keyword | 空 | 搜尋用 |
| category_type | `shopee` | **必填**，空值會回 10006 |
| category_id | `-1` | 全分類 |
| page_size / page_num | 100 / 1.. | 分頁抓全店（Lady 店 total=437） |
| order_type | `confirmed` | |
| order_by | `confirmed_sales.desc` | |

回傳 `result = {total, items[]}`，**每個 item 49 個欄位**：

- 識別：`id, name, image, status, display_tag_label`
- 曝光/點擊：`product_card_impressions, unique_product_card_impressions, product_card_clicks, unique_product_card_clicks, ctr, search_clicks`
- 流量：`uv, pv, likes, bounce_visitors, bounce_rate`
- 加購：`add_to_cart_units, add_to_cart_buyers`
- 銷售（placed/paid/confirmed 三態各一組）：`*_sales, *_units, *_buyers, *_orders, *_sales_per_order`
- 轉換率：`placed/paid/confirmed_order_conversion_rate, uv_to_*_rate, placed_to_paid_buyers_rate` 等
- 回購：`repeat_*_order_rate, average_days_to_repeat_*_order`
- **`models[]`**：規格層（inline，不用另打），每個 model 24 欄：`id, name, status, add_to_cart_*, placed/paid/confirmed_sales/units/buyers, repeat_*` 等

⚠️ 已知缺口：model 沒帶「商品選項貨號」（Excel 匯出有）。要跟訂貨/庫存系統 join 需另建 model_id ↔ 商品選項貨號 對照（商品列表 API 或用 name 對）。

## 2. 每日大盤（= sales_overview 匯出）

`GET /api/mydata/v3/sales/overview/funnel/` — 當日彙總 + 昨比
參數：`period, start_time, end_time`

回傳（節錄）：`shop_uv, hybrid_uv, placed/paid/confirmed_buyers, placed/paid/confirmed_sales`（各為 `{value, ratio}`，ratio = 相對前期）+ `*_sales_per_buyer, shop_uv_to_*_rate` 等轉換鏈。

`GET /api/mydata/v3/sales/overview/trends/` — 同參數，回每指標 24 個小時點 `[{timestamp, value}]`（要看時段分布才需要）。

## 3. 來源拆分 + 關鍵指標（= shop-stats 匯出）

`GET /api/mydata/v1/dashboard/traffic-sources/`
參數：`period, start_time, end_time, order_type=confirmed, need_paid_ads_data=true`

回傳 `result.overview`：
`total_sales, product_card(商品卡), live(直播), video(短影音), affiliate(聯盟), paid_ads(廣告)` — 各含 `_pct_diff`（昨比）與 `_ratio`（佔比）。
另有 `result.product_card.{...}` 等每來源的細分結構（含逐商品貢獻，`/traffic-sources/product-contribution/` 可再展開）。

`GET /api/mydata/v3/dashboard/key-metrics/`
參數：`period, start_time, end_time, fetag=fetag`

回傳：`shop_pv, shop_uv, product_clicks, hybrid_uv, place/paid/confirmed_gmv, *_orders, *_sales_per_order, shop_uv_to_*_buyers_rate` 等（各為 `{value, ratio}`）。

## 其他已看到但第一階段不用的端點

- `GET /api/mydata/v2/product/overview/`、`/metric-trends/`、`/v3/product/overview/product-rankings/`（商品概覽頁）
- `GET /api/mydata/v1/product/traffic/overview/`、`/item-list/`（商品流量頁，`l1_source` 可篩來源）
- `GET /api/mydata/traffic/dashboard/overview|trend/`（流量 tab，參數 `dt=YYYYMMDD`）
- `GET /api/mydata/v3/dashboard/product-rankings/`（概覽頁 Top 商品）
- 訂單 `/portal/sale/order`、廣告 `/portal/marketing/pas/index` — #S097 列為待探，第二階段再說

## 多賣場

同一套端點，換 cookie 即換店：`config/shopee_cookies_{shop}.json`（nail / lady / baby）。
第一階段先做 nail（美甲）。
