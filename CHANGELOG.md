# Changelog

## 2026-04-10

### 新增
- 完整商品資料爬取：標題、店鋪、階梯價、商品屬性、SKU（含圖片）、影片、店鋪評分
- `scraper/data_extractor.py` — 從 `__INIT_DATA__` 等 JS 全域變數提取結構化資料
- `scraper/ai_generator.py` — Claude API 自動生成蝦皮繁中標題+描述（含蝦皮合規規則）
- `scraper/shopee_excel.py` — 自動填入蝦皮 44 欄批次上架 Excel 模板
- `scraper/pipeline.py` — 串接全流程：JSON → 下載圖片 → AI 生成 → 蝦皮 Excel
- `scraper/login.py` — Playwright persistent context 登入模組（備用）
- CLI 子命令架構：`login`、`scrape`、`generate`
- 圖片下載支援 SKU 圖片（`download_product_images_from_json`）
- `.env` 管理 API key

### 變更
- `models.py` 擴充：新增 `PriceRange`、SKU `image_url`、商品屬性/分類/影片/店鋪評分等欄位
- `browser.py` 改為 persistent context 架構（登入狀態持久化）
- `item_page.py` 整合 data_extractor，DOM 改為 fallback
- `main.py` 從單一指令改為 Click group（login/scrape/generate）
- User-Agent 更新為 Windows Chrome 131
