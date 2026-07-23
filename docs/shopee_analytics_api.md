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

## 4. 廣告活動報表（#S100 探勘定案）

`POST /api/pas/v1/homepage/query/`（**注意是 POST + JSON body，不是 GET**；SPC_CDS 仍走 query）
body：`{"start_time": <epoch秒>, "end_time": <epoch秒>, "offset": 0, "limit": 100, "filter": {"campaign_type": "cpc_homepage_v3"}}`

- `campaign_type` **必填**，錯值時 API 會吐出完整枚舉表。`cpc_homepage_v3` = 首頁聚合視圖，**一次涵蓋 product/shop 全部 CPC 類型**（product_manual/product_mpd/shop_auto/shop_manual…）。
- 回 `data.entry_list`（每活動一筆）+ `data.total`（含歷史所有活動，nail=1882）。**翻頁用 offset/limit**。
- 每筆 entry：`title`(活動名) / `type` / `state`(ongoing/paused) / `campaign.{campaign_id,daily_budget,total_budget,start_time}` / `report`(36 指標)。
- `report` 核心：`cost`(花費) `impression` `click` `ctr` `cpc` `cpm` `atc`(加購) `checkout` `cr`(轉換率) + 廣義/直接兩套歸因 `broad_/direct_` 的 `order/gmv/roi/cir`。
- ⚠️ **金額欄單位 = 值 ÷100000 得「元」**：`cost/cpc/cpm/broad_gmv/direct_gmv/daily_budget/total_budget`（實測 cost 2588884→$25.89… 校驗 daily_budget 50000000→$500 合理）。
- 落地策略：**翻頁抓全 total，但只留當天有跑的活動**（`cost>0 或 impression>0`）——1882 個活動多數 paused，nail 昨日僅 11 個活躍。
- 口徑提醒：廣告 `broad_gmv`（廣告歸因成交）與大盤 `src_paid_ads`（流量來源=廣告的確認銷售）**不同口徑、不會相等**，各自有用途。

## 訂單（第二階段，走匯出檔非 API）

`/portal/sale/order` 是完整 portal SPA，無頭瀏覽器一開即被風控重導 login、純 API 路徑試 8 變體全 404。
**定案改走加密匯出檔**（同訂貨系統 `shopee_export.py` 的 msoffcrypto 解密），做商品聯動 basket 分析。

## 其他已看到但第一階段不用的端點

- `GET /api/mydata/v2/product/overview/`、`/metric-trends/`、`/v3/product/overview/product-rankings/`（商品概覽頁）
- `GET /api/mydata/v1/product/traffic/overview/`、`/item-list/`（商品流量頁，`l1_source` 可篩來源）
- `GET /api/mydata/traffic/dashboard/overview|trend/`（流量 tab，參數 `dt=YYYYMMDD`）
- `GET /api/mydata/v3/dashboard/product-rankings/`（概覽頁 Top 商品）
- 訂單 `/portal/sale/order`、廣告 `/portal/marketing/pas/index` — #S097 列為待探，第二階段再說

## 多賣場

同一套端點，換 cookie 即換店：`config/shopee_cookies_{shop}.json`（nail / lady / baby）。
第一階段先做 nail（美甲）。

## 5. 自動選品廣告逐商品明細（GMV MAX detail，#S100 攔真實匯出得出）

自動選品（全賣場推廣）UI 只顯示活動層一列（演算法黑箱），但「匯出數據→自動選品廣告詳情數據」
拆得出逐商品。佔整體廣告 ~3 成金額（實測 3,680/13,128），必須拆解才不是半盲飛。
匯出背後是 export_job API（**全部 POST**，SPC_CDS 走 query），可全自動：

1. `POST /api/pas/v1/report/export_job/trigger/`
   body `{"language":"zh-Hant","report_type":"product_gms__homepage","start_time":<epoch秒>,"end_time":<epoch秒>}`
   → `{export_id}`
2. `POST /api/pas/v1/report/export_job/get_single_result/` body `{export_id}`
   → 輪詢 `{status:"processing|success|fail", progress}`（實測 ~3-6 秒 success）
3. `POST /api/pas/v1/report/export_job/download/` body `{export_id}`
   → `{file_name, content}`，content 是 CSV 全文（前 7 列 metadata、第 8 列表頭、
     第 9 列起資料；首筆是 Shop GMV Max 聚合列 product_id='-' 要排除）

- 其他 report_type（同機制可撈）：`總體廣告數據`/`關鍵字-版位層級` 等匯出檔也走這條 export_job flow。
- CSV 金額欄已是「元」不用換算；逐商品加總 = 聚合列（實測 74 商品加總 3,680.85 = Shop GMV Max 花費）。
- 用途：挑「自動試出的高 ROAS 商品 → 轉手動加碼」（如 AS 質感方瓶基礎膠 ROAS 16.2）。
- 落地：SQLite `gms_product_daily` + Sheet「自動選品商品_YYYYMM」分頁。
