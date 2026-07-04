# Changelog

## 2026-07-05（晚上：可正常匯入後的調整）

### 修復（正確賣場模板 + 簡繁/斤→公斤，Edwin 上架前發現）
- **不同賣場模板不同**：正式賣場(293574921)模板 hash b4e5e725/43欄，與另一賣場(462676)的 3e680443/44欄不同 → 換用正式賣場那份（動態欄位對應自動吃 43/44）
- **全文字簡繁轉換**：加 opencc s2twp，標題/詳情/顏色選項/尺碼選項上架前一律轉繁體台灣。根因是 `_apply_style_filter` 用 1688 原始簡體 key 覆蓋掉 Claude 已轉的繁體 color_map（如 天蓝→應為天藍）
- **尺碼斤→公斤**：`_prepare_product` 尺碼改用 Claude 的 size_labels keys（已正規化 S/M/L、值已換算 kg），不再用 product_data["sizes"]（1688 原始 "S(60-80斤)" 對不上 labels 而漏出斤）
- ✅ 雙商品重驗：顏色 天藍/蘇粉/釉藍、尺碼 S（30-40 kg）、無簡體無斤


### 新增（雙商品最終跑批 — P-a1 寬褲 + P-b1 T恤）
- CATEGORY_MAP 補上 T恤/上衣/短袖/襯衫（100352/100356/100353）
- 影片也尊重 `image_skip`：排除有簡體的主圖不進影片（P-a1 排 main_000）
- 尺碼表繁體版走素材夾手動上傳（Q 欄不放 1688 簡體圖，保持乾淨）
- P-b1（莫代爾短袖T恤 1057125777540）：Chrome MCP 抓取 → 5色×5尺碼25SKU、分類100352、體重制尺碼表
- ✅ 雙商品合併 Excel：識別碼1(P-a1 21SKU/100358/998)+識別碼2(P-b1 25SKU/100352/398)=46 SKU；各自影片+尺碼表歸素材夾


### 變更（回到 1688 原圖，排除簡體封面）
- 決定商品圖用 1688 原圖、不走 GPT（GPT 生圖模組 gpt_image_generator.py 保留備用，Edwin 覺得還要再調）
- `build_two_tier_rows` 加 `config["image_skip"]`：排除有簡體字的主圖 index；P-a1 排除 main_000（含「冰丝 阔腿裤」簡體），封面改用乾淨 main_001


### 變更（影片改用乾淨穿搭圖）
- **影片選圖邏輯**：`collect_images` 改「主圖 + SKU 優先、detail 最後」（1688 的 detail 幾乎都是簡體行銷文案圖/尺碼表，不適合上架；主圖是乾淨模特兒穿搭）；預設取前 n 張不再隨機
- `make_product_video` 加 `images=` 參數：可傳入人工挑好的乾淨穿搭圖清單（按序）
- P-a1 影片改用人工挑的 9 張乾淨穿搭圖（無簡體字，色系齊全 米白/咖啡/黑，全身+站+坐+平拍）

### 變更（Edwin 實測可匯入後要求）
- **主商品貨號填回編號 + 型號留空**：可匯入版基礎上，`ps_sku_parent_short` 填編號（庫存商品識別）、`ps_sku_short`（型號）改**全留空**。此組合合法（商品層用主貨號、變體靠規格選項辨識），不觸發「型號與變體不匹配」
- **圖片尺寸表（Q 欄 et_title_size_chart）**：`build_col_map` 補上此欄 key；`build_two_tier_rows` 支援 `config["size_chart_url"]` 每行填圖片網址。P-a1 用 1688 尺碼表（detail_020）CDN 網址
- **`scraper/size_chart_maker.py`**：用尺碼數據重繪乾淨繁體尺碼表 PNG（去掉 1688 簡體版的九分褲等不相關欄）。P-a1 產出 `output/784712770291/images/generated/size_chart_P-a1.png`（供 Edwin 上傳蝦皮取得網址後替換 Q 欄）

## 2026-07-05（傍晚：新模板 + 主貨號留空修復）

### 修復（實測第三輪 — 資料整片不進的兩個元兇都拔掉）
- **型號（ps_sku_short）改回「每個顏色一個」**（`P-a1-1/2/3`），取代測試版的「每 SKU 唯一」（`P-a1-1-S`）。實測：每 SKU 唯一 → 蝦皮判「型號與變體不匹配」、資料整片不進（型號對應第一軸顏色，不含尺碼軸）。完全對齊過審版 commit d36a6f6
- 診斷方法：openpyxl/ET 驗證 XML 皆 well-formed（排除結構壞檔）→ 6/30(過審) vs 7/5(空) 模板結構逐項比對幾乎相同（排除模板）→ 鎖定是 code 偏離過審設定（測試版改了 parent_sku + option_sku 兩處，前一輪只revert前者）
- 不影響庫存：庫存系統解析「規格選項1/2」（編號_簡稱_顏色 / 尺碼），非 ps_sku_short；尺碼資訊在規格選項2

### 修復（實測第二輪）
- **換用蝦皮 2026-07-05 最新模板**（43→44 欄、hash `b4e5e725…`→`3e680443…`、物流頻道移除 30012 加 30010/30011）。舊模板輸出被判「需更新最新版本」= 黃金規則 #1。產檔 code 無須改（動態欄位對應自動吃）
- **主商品貨號改回留空**：測試版填回 `P-a1` 上新模板 → **上傳成功但資料整片不進**（蝦皮判「型號與變體不匹配」靜默丟列）。黃金規則 #9 第二次血淚確認。型號 `option_sku` 每 SKU 唯一（`P-a1-1-S`）保留—非元兇、庫存要

## 2026-07-05（凌晨-下午）

### 新增（過審二階路徑固化成 CLI + 批次串接器 + 影片整合）
- `main.py generate2` — 單商品過審二階路徑正式入口：串 `copywriter.generate_listing` + `build_variants` + `generate_two_tier_excel`（#S064 過審路徑以前只存在臨時 inline 呼叫，現固化）。支援 `--colors "src=乾淨名"` 挑色清名、`--reuse-content` 用 ai_content.json 快取不重呼 Claude
- `main.py batch2` + `scraper/batch_pipeline2.py` — 批次過審二階路徑：讀 manifest → 逐商品文案+變體（**+短影片**）→ 合併成**一個**蝦皮 Excel
- **影片整合進 batch2**：每商品順便合成 1:1 短影片（`--video/--no-video`，預設開）；影片吃本機圖，缺圖會先自動下載再合成。P-a1/P-a2 實測各 1080×1080、18.5s、~2MB
- `shopee_excel.generate_batch_two_tier_excel` — 多商品合併寫入器：**每商品一個遞增規格識別碼**（1,2,3…），是蝦皮把多列歸成同商品又不互相混淆的鑰匙
- `config/batch_manifest.example.json` — 批次清單範例（item_id / 編號 / 售價 / 分類 ID / 挑色）
- ✅ 實測：P-a1(長褲) + P-a2(九分褲) 兩商品跑 batch2 → 合併 42 SKU，識別碼 1/2 分開、型號全唯一無中文、售價各異、模板 14/16 檔原封不動

### 新增（AI 上架名單驅動 — 端到端第一次測試通過）
- `scraper/ai_list_reader.py` — 讀「【Lady】AI 上架名單」Google Sheet（給 AI 用的調整版）→ 轉 batch2 輸入。這版把採購表缺的都補上了：**J 編號、K 純文字 1688 網址、F 分類、L 款式（挑色 hint）、M 尺寸、T 售價**。含 `CATEGORY_MAP`（分類文字→蝦皮 ID，如 長褲→100358）
- `batch2 --ai-list <csv>` — 直接吃 AI 名單 CSV（Chrome 同源下載落地）自動跑，不必手寫 manifest
- `batch_pipeline2` 加 `_apply_style_filter`：AI 名單「款式」欄（如「三色長褲」）配合抓到的色卡自動挑色 + 清乾淨顏色名（去【長褲】款式括號）
- ✅ **端到端第一次測試**：AI 名單 → 讀 P-a1 → Claude 文案 → 款式挑色（3 長褲色）→ 影片 → 21 SKU Excel，逐欄對齊過審檔（分類100358/售價998/識別碼/型號無中文/模板14-16原封）

### 決策：批次用 manifest / AI 名單，不解析人工採購表
- 人工採購表（`【女性周邊】2. 採購商品表`）**沒有「編號」、沒有「蝦皮分類 ID」**，1688 網址是超連結（gviz CSV 讀不到 target）。→ 改用**專門給 AI 的「【Lady】AI 上架名單」**（純網址+編號+分類+款式+售價），或手寫 manifest。編號/分類 ID/挑色都是人為決策，落地才穩

### 測試中
- 蝦皮 Excel 測試版：在過審版基礎上把「主商品貨號」加回編號、「商品選項貨號(型號)」改成每 SKU 唯一（`P-a1-1-S` 色序+尺碼），待實測是否仍過審；若觸發「型號與變體不匹配」則主商品貨號改回留空

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
