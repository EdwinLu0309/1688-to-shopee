# TODO

## 高優先
- [x] 2026-07-05 ★桌面 GUI（`gui.py`，tkinter Win/Mac）：🔑登入 → 🔍抓取（Playwright+cookie）→ ▶產Excel（batch2）→ 📁素材夾。`scraper/playwright_scraper.py` 正式化去風險腳本；`run_mac.command`/`run_windows.bat` 啟動
- [x] 2026-07-05 ⚠️→✅ 測試版 `parent_sku` 填回編號**實測失敗**（新模板：上傳成功但資料整片不進）→ 已改回**留空**（黃金規則 #9 第二次血淚確認）；型號 `option_sku` 每 SKU 唯一保留（庫存用，非元兇）
- [ ] GUI 用 Edwin 實機驗證（登入→抓取→產Excel→補素材）
- [x] 2026-07-05 主圖抓滿：改讀 JS `offerImgList`（非只 DOM 縮圖）→ P-a1 由 5 張補回 9 張（extract_1688.js + playwright_scraper.py 兩邊都改）
- [x] 2026-07-06 ★AI 名單改「表頭名稱」對應（不寫死欄號）+ 分類欄空白時從商品名推斷分類 ID。踩坑：Edwin 在線上表插「廠商」欄→款式/尺寸/售價整排右移，舊版寫死欄號全錯位
- [x] 2026-07-06 分類 ID 從模板「較長備貨天數範圍」sheet 取真實 ID（長褲/牛仔褲/短褲/褲裙/裙裝/T恤），CATEGORY_MAP + 商品名推斷雙軌
- [x] 2026-07-06 ★AI 名單 CSV 落地做成一鍵（路 B）：`chrome_cookies.py` 解密日常 Chrome 的 Google cookie + `sheet_fetcher.py` httpx 打 gviz → GUI「⬇️ 更新名單」/ CLI `fetch-list`。免登入、自動掃 profile。實測抓到 live 48 商品名單
- [x] 2026-07-06 ★GUI 加逐商品勾選清單（可捲動 + 全選/全不選）：抓取/產出都只做勾選的，先勾 1-2 筆試跑再全選
- [x] 2026-07-07 #S068 ★公司 Windows 可跑化：Chrome cookie 全 v20(App-Bound) 解不開 → 改 `scraper/google_login.py`（Playwright 真實 Chrome 登入一次存 session）；`chrome_cookies.py` 補 Windows DPAPI(v10/v11 可解 v20 跳過)；`sheet_fetcher` 多來源；GUI「🔑 Google 登入」+ CLI `google-login`；修 cp950 崩潰(settings.py UTF-8)；ffmpeg 跨平台(imageio-ffmpeg)。建 `.venv`(Py3.14)+全 deps
- [ ] Edwin 在公司 Windows 實跑驗證：🔑 Google 登入一次 → ⬇️ 更新名單 → 抓取 → 產 Excel 全鏈
- [ ] 公司 Windows `.env` 若要用 ✨GPT 生圖路線，補 OPENAI_API_KEY + SUPABASE_URL/SERVICE_KEY/BUCKET
- [x] 2026-07-06 ★顏色/尺寸選項政策（100 SKU 上限）：尺寸+身高款全留、只砍顏色到中性≤5、流行色不進貨、100 保底。兩層：款式備註(Claude style_kept) → 中性色政策。第一軸「顏色×身高款」認底色綁組不拆散。實測 P14AE1 4底色×3身高款×6尺碼=72、P14AE2 24 SKU
- [ ] 48 商品整批實跑驗證（2 筆已跑通；全選全跑 scrape 48 + 文案 + 影片 ~30-40min）
- [ ] 分類推斷偶爾要人工覆核（如「花苞短裙…裙裤」歸褲裙 vs 裙裝）；Edwin 填分類欄可覆寫
- [ ] 牛仔褲類「復古藍/牛仔藍」會被當流行色砍（只留黑/白）；若要保留丹寧藍需在款式欄指定或擴充中性色定義
- [ ] GUI 抓取穩定度：批次抓多商品時的節流/重試；被擋自動退回路A（Chrome MCP）提示
- [x] 2026-07-09 #S070 ★訂貨表結構建好（Google Sheet 3 分頁：`1_訂貨主檔` SKU↔1688 對照 / `2_每日訂購彙總` 訂貨依據 / `3_訂單明細` 按訂單編號出貨依據）。join key=商品選項貨號（實測蝦皮吃）、規格一實測逐字對上 1688。SA `inventory-sync@…` 寫入
- [ ] #S070 ★做獨立簡易版下單工具：匯入蝦皮 Excel（msoffcrypto 解密）→ 建當日分頁明細+彙總 → 顯示今日總金額 → 帶 1688 cookie 點下單呼叫 1688-order `cart_adder` → 回寫狀態 → 點核對跑 `cart_verifier`
- [ ] #S070 規格二尺碼格式（`S（80~95斤）`）待 cart_adder 首次實跑驗；確認 1688 單軸(色-款式)或雙軸(含尺碼)決定下單聚合顆粒度
- [x] 2026-07-09 #S070 ★走 A 全自動圖片 pipeline：`auto_classify.py`（vision 自動挑全身圖+讀尺碼表）+ `scratch_auto_pipeline.py`（分類→轉換→尺碼表，3緒+退避）→ 分頁014(43支)+分頁15(13支)實跑通
- [x] 2026-07-09 #S070 ★尺碼公斤三層源頭修（copywriter prompt + build_variants clean key/kg label + scrub_jin 掃詳情）；買家kg／貨號純字母／訂貨表規格二用 JSON 原始斤 分離
- [ ] #S070 訂貨表產生器：規格二務必用 JSON 原始 `sizes`（斤）對回，不可用清過的 size key（P14AE12「M【80-100斤】」會對不到）
- [ ] #S070 走 A 正式接進 `gpt_image_generator`/GUI（現為 scratch）；改善主圖類簡體側欄翻繁（P14AE28/29/41）；分類器對安全裤類全身圖少的調整
- [ ] #S070 補 P14AE4/P14AE5 的 1688 進貨單價（現 ¥0，影響訂貨成本計算）
- [ ] #S070 Edwin 上架商品時驗證「商品選項貨號」蝦皮完整吃下（訂貨 join 地基）；上架用轉換圖 Excel（`測試5_shopee_轉換圖.xlsx` 這類）+ 素材包
- [ ] 選項勾選表（兩軸 → 人工勾選上架哪些 + 訂貨數量）

## 中優先
- [ ] 商品簡稱自動生成（1688 名 → 繁體台灣用語，無中國用法）
- [ ] 尺碼體重/身高對照（廠商文字有就帶；只在圖片裡的待自動讀圖）
- [ ] 圖片後製介面串接（對接圖片處理專案）
- [ ] 影片來源改 GPT 電商圖（目前用 1688 圖跑通）

## 低優先
- [ ] Chrome CDP 批次爬取（取代手動 Chrome MCP）
- [ ] 批次處理進度報告

## 已完成
- [x] 2026-07-05 ★AI 名單驅動端到端跑通：`ai_list_reader` 讀「【Lady】AI 上架名單」→ `batch2 --ai-list`；款式「三色長褲」自動挑色、分類→ID、影片整合。第一次測試 P-a1 21 SKU 逐欄對齊過審檔
- [x] 2026-07-05 ★影片合成整合進 batch2（每商品順便出 1:1 短影片，缺圖自動先下載）
- [x] 2026-07-05 ★過審二階路徑固化成 CLI（`generate2` 單商品 / `batch2` 批次）+ `generate_batch_two_tier_excel` 多商品合併（每商品遞增識別碼）+ manifest 輸入；P-a1+P-a2 實測 42 SKU 合併過審格式
- [x] 2026-06-30 ★蝦皮二階上架 Excel 實測過審（P-a1 冰絲寬褲 21 SKU）— 黃金規則見 CLAUDE.md
- [x] 2026-06-30 文案引擎 copywriter.py（Claude + 女裝 SOP，標題/詳情/簡稱/變體命名）
- [x] 2026-06-30 影片合成模組 video_maker.py（683/784 實測各 18.5s 1:1 mp4）
- [x] 2026-06-30 抓取升級兩軸（尺碼 + 屬性 + 單價 + 各尺碼庫存）
- [x] 2026-06-30 修跨 event loop Semaphore bug（批次第二個商品起少圖）+ 下載重試
- [x] 2026-06-30 採購表讀取（你登入 Chrome 同源讀 CSV，純網址）
- [x] 2026-06-29 固化 1688 抓取（extract_1688.js）取代失效的 __INIT_DATA__
- [x] 2026-06-29 新增 images 指令批次下載圖片（683456636600 實測 47 張）
- [x] 2026-04-12 Google Sheet 採購表讀取（64 筆商品解析）
- [x] 2026-04-12 Gemini 取代 Claude（多模態文案+圖片生成）
- [x] 2026-04-12 批次 Pipeline + batch CLI command
- [x] 2026-04-12 蝦皮 Excel 改為模板 zip 直接修改（保留隱藏 sheet）
- [x] 2026-04-12 單商品完整 pipeline 驗證（782115160713 防曬面罩）
- [x] 2026-04-10 1688 單一商品完整爬取（Chrome MCP）
- [x] 2026-04-10 圖片下載（主圖+細節+SKU，75張）
- [x] 2026-04-10 Claude AI 生成蝦皮標題/描述
- [x] 2026-04-10 蝦皮批次上架 Excel 自動產生
- [x] 2026-04-10 完整 pipeline 跑通（651869906762 甲油膠）

## GPT 生圖路線（2026-07-06～08）
- [x] ✨GPT 支線接回：`image_host.py`（Supabase 圖床）+ batch route + GUI 每支勾選 + 成本確認。全鏈實測通
- [x] 2026-07-08 ★引擎轉向：設計規範改單一宣告式 `design_engine/JOYSLU_LADY_DESIGN_ENGINE.md` V1.0；`gpt_image_generator` 改「讀 md + 組圖 + 呼叫 API」；模型 gpt-image-1
- [x] 2026-07-08 ★Sprint B 驗證：Responses API（gpt-5.5 導演 + image_generation + previous_response_id 串接）完勝 images.edit（文字全繁體、GPT 自主規劃整套 9 張）。原型在 `scratch_listing.py`
- [ ] ★把 Responses API 串接 + V1.0 正式接進 `gpt_image_generator`（取代 images.edit）、清 `scratch_*.py`
- [ ] ★跑一次帶 usage 記錄拿真實 token 成本 → 省錢（參考圖 15→6-8、品質分段 medium 草稿→high 定稿）
- [ ] Edwin 續調 V1.0 spec + persona（板娘臉一致性：目前是自然模特兒臉、未必本人）
- [ ] ★用 Supabase URL 塞蝦皮 Excel 上傳測 1 張，確認蝦皮抓得到公開圖不被擋，再全量
