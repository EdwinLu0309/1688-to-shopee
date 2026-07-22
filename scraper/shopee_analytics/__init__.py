"""蝦皮賣家中心「數據中心」每日數據抓取套件。

三張核心表（承 #S097 設計，詳見 docs/shopee_analytics_api.md）：
- 商品明細（parentskudetail）：/api/mydata/v4/product/performance/
- 每日大盤（sales_overview）：/api/mydata/v3/sales/overview/funnel/
- 來源拆分（shop-stats）：/api/mydata/v1/dashboard/traffic-sources/ + key-metrics

儲存：raw JSON 快照（原封存檔）→ SQLite 副本 → Google Sheet（真相來源，Edwin 可親自核對）。
"""
