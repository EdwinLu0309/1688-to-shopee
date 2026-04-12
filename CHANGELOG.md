# Changelog

## 2026-04-12

### 新增
- `scraper/gemini_generator.py` — Google Gemini 多模態生成蝦皮文案（標題+描述）+ 電商產品圖片，取代 Claude API
- `scraper/sheet_reader.py` — Google Sheet 採購表讀取器，自動提取超連結中的 1688 URL
- `scraper/batch_pipeline.py` — 批次處理 Pipeline，逐一處理每個商品（下載圖→文案→生圖），支援 resume
- `scraper/shopee_excel.py` 新增 `generate_batch_shopee_excel()` 多商品合併為單一蝦皮上傳 Excel
- CLI 新增 `batch` 子命令（從採購表批次處理所有商品）
- `config/settings.py` 新增 Gemini API、Google Sheet 設定

### 變更
- `shopee_excel.py` 改為直接修改模板 zip 結構（保留隱藏 sheet 和 metadata），解決蝦皮上傳驗證失敗問題
- 每個 SKU 行都填入商品名稱（蝦皮要求每行都有）
- `requirements.txt` 新增 `google-genai`

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
