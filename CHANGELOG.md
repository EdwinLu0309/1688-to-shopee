# Changelog

## 2026-06-30（下午：文案引擎 + 蝦皮二階上架實測過審）

### 新增
- `scraper/copywriter.py` — 文案引擎：Claude + 女裝 SOP 生標題/詳情/商品簡稱（繁體台灣用語）/flags；`build_variants()` 拼蝦皮二階規格選項名（`編號_簡稱_顏色` / 尺碼）
- `config/sop/` — 收進女裝 SOP（03f）+ 母規範 v2.4 + 視覺風格規範
- `shopee_excel.py` 新增 `generate_two_tier_excel` / `build_two_tier_rows` / `build_col_map` / `_insert_data_rows` — 二階規格（顏色×尺碼）上架

### 變更
- 蝦皮 Excel 產檔改為「只插入資料列、模板 100% 原封不動」：保留版本 hash、sharedStrings 只追加、資料從第 7 列起、用 sharedStrings 而非 inlineStr
- 欄位改用模板內部 key 動態對應（吃不同版本模板：43/44 欄、物流頻道變動不跑版）
- `config/shopee_template.xlsx` 換成 2026-06-30 最新模板

### 修復（實測過審逐條）
- 數字欄寫文字字串（避免 Go ParseUint 讀成 "1.0" 失敗）
- 商品規格識別碼每列同值（歸成一個商品，否則 SKU 被拆成獨立商品）
- 主商品貨號 / 危險物品留空、商品選項貨號純英數（否則「型號與變體不匹配」）
- 分類填分類 ID（100358 女生衣著/長褲）；物流啟用填「開啟」停用留空
- ✅ 商品 P-a1（冰絲寬褲 3 色×7 尺碼 21 SKU）實際匯入蝦皮**過審成功**

## 2026-06-30

### 新增
- `scraper/video_maker.py` — 蝦皮商品短影片合成（本機圖片 → 1:1 mp4，移植自 listing-optimization-tool 的 ffmpeg 合成核心）。`make_product_video()` 隨機挑 N 張圖、淡入淡出、≥11 秒、自動配樂

### 變更
- `scraper/extract_1688.js` 升級為**兩軸抓取**：除第一軸（顏色/款式 `.sku-filter-button`）外，新增第二軸尺碼（`sizes`）、商品屬性表（`attributes`，Ant Design 表格，供文案規格欄）、1688 單價（`price_cny`）、各尺碼價格/庫存（`size_stock`）。先前只抓到顏色軸、完全漏掉尺碼

### 修復
- `scraper/downloader.py` 修掉**跨 event loop 的 Semaphore bug**：原 module 層級 `asyncio.Semaphore` 綁第一個 loop，`images` 指令對每個商品各跑一次 `asyncio.run()`，第二個商品起會用到已關閉舊 loop 的 semaphore → 大量少圖（症狀：第二個商品只下到 5/5/5）。改為每次呼叫建立 semaphore + 下載失敗指數退避重試 3 次

## 2026-06-29

### 新增
- `scraper/extract_1688.js` — 現行 1688 抓取邏輯（Chrome MCP 注入）：抽主圖/SKU 色卡/細節圖 → Blob 下載 `{item_id}.json`。取代已失效的 `__INIT_DATA__` 提取
- CLI 新增 `images` 子命令 — 批次下載 1688 圖片（讀抓出的 JSON，不經 AI），支援 `--ingest-downloads` 自動從 `~/Downloads` 搬入

### 變更
- `CLAUDE.md` 更新抓取流程說明：標注 `data_extractor.py`（`__INIT_DATA__`）已失效、記錄現行 DOM 選擇器、說明為何只能用 Blob 下載落地（CSP/剪貼簿/MCP 截斷皆不可行）
- `.gitignore` 新增 `AI-Memory/`、`.pytest_cache/`

### 修復
- 環境驗證：1688 反爬下抓取改走 Chrome MCP + DOM 選擇器（`.od-gallery-list` / `.sku-filter-button` / `offer_details.content`），單商品 683456636600 實測抓到 15 主圖 / 22 細節 / 10 SKU 並完整下載

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
