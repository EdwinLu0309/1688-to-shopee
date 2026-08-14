# 1688-to-shopee

## 專案簡介
1688 商品資訊爬取 → AI 生成蝦皮文案 → 蝦皮批次上架 Excel 自動產生。

## ⚠️ 六子系統拆解已收官（#S130/S134）— 本 repo ＝純上架系統
六子系統全數拆解完畢，**本 repo 只剩「1688 商品→蝦皮上架」本業**（爬取→AI 文案→蝦皮 Excel + 商品資產包）：
- **⑤ 蝦皮後台分析** → `shopee-analytics` repo（排程 plist 指新 repo；`run_shopee_analytics_install.command` 與孤兒 plist 已於 #S134 清除）。
- **④ Kkren 到貨** → `kkren-sync` repo。
- **① 1688 抓取** → `ecommerce-sources.alibaba1688`；**⑥ 素材** → `ecommerce-media`（5 模組，本 repo 為 re-export shim）；**讀表** → `ecommerce-sources.gsheet`。
- **②③ 訂貨/對帳** → `1688-order` repo（#S134）。`scraper/ordering/` 整包 + order_gui/reconcile_gui + 訂貨/對帳啟動檔 + main.py 的 order-*/reconcile-refresh 命令全部移除（-4723 行）。**架構原則：上架（本 repo）vs 訂貨（1688-order）是兩件事，「預購」只是橫跨兩者的模式。**

## ★三賣場化（#S165，2026-08-14）— 上架支援 Nail / Lady / Baby
上架 pipeline 從 Lady 單賣場版改為三賣場：**賣場設定單一正本＝`scraper/shops.py`**（ShopProfile：
品牌標籤/名單 Sheet/模板/cookie key/分類對照/SOP/選項政策/物流/軸名），其他模組帶 `shop` 參數查表。
**規則依據與草案狀態見 `docs/三賣場上架依據.md`**（標題公式、per-shop 選項政策、Edwin 待辦）。
- GUI 最上方「⓪ 賣場」下拉切換（名單/登入帳號/模板/SOP 全跟著換）；CLI `fetch-list`/`batch2` 加 `--shop`。
- **模板 per-shop**：`config/shopee_template_{shop}.xlsx`（模板藏版本 hash＋物流欄位是賣場設定，
  絕不可跨賣場共用；lady 暫 fallback 舊檔 `shopee_template.xlsx`）。缺件明確報錯，不靜默用錯賣場的。
- **名單 per-shop**：`.env` 設 `AI_LIST_SHEET_ID_{SHOP}`（表分享給 inventory-sync SA）→ `input/{shop}_ai_list.csv`。
- **選項政策分流**：lady=`clothing`（中性色 ≤5 底色政策不變）；nail/baby=`cap_only`（色號/花色是商品
  本體不砍色，只守 100 SKU 上限）。分類 ID 三賣場共用同一套分類樹（模板分類表 2012 個全品類），
  各賣場的 category_map/name_rules ID 皆取自模板真實 ID。
- 文案 system prompt 改字串拼接組裝（SOP 含大括號不會炸 .format）；Nail/Baby SOP 為草案
  （`config/sop/{shop}/…草案v0.md`），校準後升版。⚠️ 批次一次跑一個賣場（混跑會讓 prompt cache 失效）。
- 產出檔名 per-shop：`output/shopee_batch_upload_{shop}.xlsx`。Lady 行為已迴歸驗證與單賣場版一致
  （P14AE1：4 底色×6 尺碼=72 SKU、標題/分類/軸名不變）。

## 技術棧
- Python 3.12（.venv；Tk 9.0 深色模式正常）
- tkinter（桌面 GUI，gui.py，Win/Mac 雙平台）
- Playwright + 登入 cookie + stealth（GUI 抓取法B，#S066 起實測可過 1688 反爬）
- Claude in Chrome MCP（抓取法A，手動注入，最保險）
- Google Gemini API（google-genai SDK，文案+圖片生成，取代 Claude API）
- Anthropic SDK（Claude API，保留備用）
- HTTPX（圖片下載）
- Click（CLI）
- openpyxl / python-calamine（Excel 讀寫）
- Loguru（日誌）
- python-dotenv（環境變數）

## 檔案結構
```
├── gui.py                     # ★桌面 GUI（tkinter，四步：登入→抓取→產Excel→素材夾）
├── run_mac.command            # Mac 啟動 GUI（優先 .venv/bin/python，Tk 9.0 深色正常）
├── run_windows.bat            # Windows 啟動 GUI
├── run_sync_assets_windows.bat # Windows 啟動資產包同步
├── main.py                    # CLI 入口（login/scrape/generate/generate2/batch/batch2/fetch-list/google-login/product-cards/sync-assets）
├── config/
│   ├── settings.py            # 全域設定（含 Gemini、Google Sheet）
│   ├── shopee_template.xlsx   # 蝦皮批次上架模板
│   ├── apps_script/           # 三賣場商品主表綁定 Apps Script（Lady/Nail/Baby Code.gs + 狀態同步外掛）
│   └── browser_profile/       # Playwright 登入 profile（gitignored）
├── scraper/
│   ├── models.py              # Product1688, SKUOption, PriceRange
│   ├── extract_1688.js        # 抓取法A：Chrome MCP 注入此 JS 抽 DOM → Blob 下載 JSON
│   ├── playwright_scraper.py  # ★抓取法B（GUI + CLI scrape 用）：Playwright+cookie+stealth 抽 DOM（免 Chrome MCP，同一套選擇器）
│   # （#S127 已移除死碼：item_page.py / data_extractor.py / network.py —
│   #   原 item_page 被反爬擋死、只剩 CLI scrape 借用；scrape 已改走 playwright_scraper）
│   ├── browser.py             # Playwright persistent context（login.py 用）
│   ├── login.py               # 手動登入模組
│   ├── downloader.py          # 圖片下載（主圖/細節/SKU）
│   ├── ai_generator.py        # Claude API 生成蝦皮標題/描述（保留備用）
│   ├── gemini_generator.py    # Gemini API 多模態生成文案+電商圖片（舊，備用）
│   ├── gpt_image_generator.py # ★GPT 生圖（gpt-image-1，讀 config/design_engine/*.md 規範 + 組圖）
│   ├── image_host.py          # ★Supabase Storage 圖床：本機 PNG → 公開 https URL（GPT 路線用）
│   ├── sheet_reader.py        # Google Sheet 採購表讀取（hyperlink 提取）
│   ├── shopee_excel.py        # 蝦皮 Excel 模板填入（zip 直改保留隱藏 sheet）
│   ├── copywriter.py          # ★文案引擎：Claude + SOP 生標題/詳情/簡稱/變體命名（build_variants）
│   ├── video_maker.py         # 蝦皮短影片合成（本機圖→1:1 mp4，ffmpeg）
│   ├── pipeline.py            # 單商品全流程串接
│   ├── batch_pipeline.py      # 批次處理（採購表→逐一處理→合併 Excel）
│   └── product_card.py        # 商品資產包（廠商固定事實商品卡 + 圖/影片/raw）
│   # （★②③ 訂貨/對帳套件 scraper/ordering/ 已於 #S134 整包遷至 1688-order repo）
├── output/                    # 產出目錄（gitignored）
│   └── {item_id}/
│       ├── ai_content.json
│       ├── shopee_upload_{item_id}.xlsx
│       └── images/
│           ├── main/
│           ├── detail/
│           ├── sku/
│           └── generated/     # Gemini 生成的電商圖
└── logs/                      # 日誌（gitignored）
```

## CLI 指令
```bash
# 登入 1688（Playwright persistent context）
python main.py login

# 爬取單一商品（Playwright）
python main.py scrape "https://detail.1688.com/offer/XXX.html" -v -j

# ★單商品「過審二階路徑」（Claude 文案 + 程式拼變體 → 二階規格 Excel）
#   --colors 可 src=乾淨名 挑色清名；--reuse-content 用 ai_content.json 快取不重呼 Claude
python main.py generate2 output/784712770291.json --code P-a1 -p 998 -s 10 -c 100358 \
  --reuse-content --colors "米白色【长裤】=米白色,黑色【长裤】=黑色,灰色【长裤】=灰色"

# ★批次「過審二階路徑」（→ 逐商品文案+變體+短影片 → 合併一個蝦皮 Excel，每商品一個識別碼）
#   輸入二擇一：--ai-list（AI 名單 CSV，推薦）或 --manifest（手寫 JSON）
#   --no-video 可關影片；影片吃本機圖，缺圖會先自動下載
python main.py batch2 --ai-list input/lady_ai_list.csv -j output -o output/lady_ai_batch.xlsx
python main.py batch2 -m config/batch_manifest.example.json -j output -o output/shopee_batch_upload.xlsx

# 批次下載 1688 圖片（讀 Chrome MCP 抓出的 JSON，不經 AI）
python main.py images --ingest-downloads

# （舊路徑，保留備用）generate/batch 走 Gemini 單階，未接過審二階格式：
# python main.py generate product.json -t config/shopee_template.xlsx -p 85 -s 5
# python main.py batch --sheet procurement.xlsx --json-dir output/ --template config/shopee_template.xlsx
```

**過審二階路徑（generate2 / batch2）＝ #S064 實測過審的正線**（單/批次）。舊 `generate`/`batch`
走 Gemini 單階、未接二階過審格式，僅備用。批次用 **manifest**（`config/batch_manifest.example.json`）
當輸入而非直接解析採購表——因為採購表沒有「編號」、沒有「蝦皮分類 ID」，且 1688 網址是超連結
（gviz CSV 讀不到 target）；編號 / 分類 ID / 挑色都是人為決策，落地成 manifest 才穩。

## AI 上架名單讀取（ai_list_reader.py）
`batch2 --ai-list` 讀「【Lady】AI 上架名單」CSV。兩個關鍵設計（都是踩坑換來）：
- **欄位靠「表頭名稱」動態對應，不寫死欄號**（`_find_header_row`+`_build_colmap`）。因為
  Edwin 會在表裡插欄/搬欄——實際踩過：插一個「廠商」欄，害款式/尺寸/售價整排右移一格，
  舊版寫死欄號（COL_STYLE=11…）整個錯位、把廠商名當款式。售價欄無表頭 → 取尺寸欄右邊
  「最後一個純數字」（跳過利潤率 65.14% 那種帶 % 的）。
- **分類欄空白 → 從商品名關鍵詞推斷蝦皮分類 ID**（`_infer_category_from_name`，規則由具體到
  籠統：裙褲→牛仔→裙→短褲→長褲→上衣）。Edwin 有填「分類」欄時優先用 `CATEGORY_MAP`。
  分類 ID 是查 `config/shopee_template.xlsx`「較長備貨天數範圍」sheet（2013 個分類）得來的真實 ID：
  長褲 100358 / 牛仔褲 100103 / 短褲 100360 / 褲裙 100361 / 裙裝 100102 / T恤 100352。

## AI 名單怎麼從 Google Sheet 落地成 CSV（走 Service Account，#S134）
名單是私有 Google Sheet（`AI_LIST_SHEET_ID`，見 settings.py）。**#S134 起走 inventory-sync SA 讀**
（該表已分享給 SA），與其他所有 Google 表統一——不再需要 Google 個人登入 cookie。
`sheet_fetcher.fetch_ai_list` 用 `ecommerce_sources.gsheet` + SA 開表 → `get_all_values()` →
寫 `input/lady_ai_list.csv`（`ai_list_reader.parse_ai_list_csv` 動態表頭對應解析）。
入口：GUI「⬇️ 更新名單」/ CLI `python main.py fetch-list`。
（原本兩條 cookie 來源＝Playwright 登入 session + 收割 Chrome cookie，連同
`google_login.py`/`chrome_cookies.py`/`google-login` 命令/gui「🔑 Google 登入」按鈕已於 #S134 退休。）
⚠️ Windows 主控台預設 cp950，輸出 ✓✗/中文會 UnicodeEncodeError → `config/settings.py` 開頭
把 stdout/stderr `reconfigure(encoding="utf-8")`（main.py 與 gui.py 都早期匯入 settings）。
⚠️ 讀舊本機 CSV = 讀到舊資料：實際踩過本機檔停在 2 商品舊版、線上表其實已 48 商品。

## 桌面 GUI（gui.py，一條龍、免打指令）
給非工程使用者的「按幾顆按鈕就上架」全包 App（tkinter，Win/Mac 雙平台）。
啟動：Mac 雙擊 `run_mac.command`、Windows 雙擊 `run_windows.bat`（皆優先用 `.venv`）。
流程：⬇️ 更新名單 → 勾選商品 → 🚀 一鍵完成（抓取→產出）→ 📁 素材。字體整體放大（可讀性）。
主按鈕是 **🚀 一鍵完成**（`_run_all_worker`：scrape_many 抓 → run_batch_two_tier 產，一次到底）；
下面「分步執行」保留 🔍 只抓取 / 📦 只產出 給需要重跑單一步驟時用。各步驟：
0. **⬇️ 更新名單** → `sheet_fetcher.fetch_ai_list`（帶登入 cookie 抓私有 Sheet；Windows 首次
   先按「🔑 Google 登入」，之後免再登；macOS 免登入自動收割）→ 覆蓋 `input/lady_ai_list.csv`
   → 解析成**逐商品勾選清單**（顯示
   編號/推斷分類/名稱）。Windows 首次先「🔑 Google 登入」；macOS 免登入自動收割。
1. **（勾選）** → 先勾 1-2 筆試跑，確認再「全選」整批（`_selected()`；抓取/產出都只做勾選的）。
2. **🔑 登入 1688** → `playwright_scraper.save_cookies` 開瀏覽器手動登入 → 存 `config/cookies.json`
   （抄 1688-order launcher 的 `_save_cookies`；偵測跳離 login 頁視為成功，最多等 5 分）。
3. **🔍 抓取商品** → 勾選商品的 item_id → `playwright_scraper.scrape_many`
   （Playwright+cookie+stealth，共用一個瀏覽器逐頁抓）→ 存 `output/{item_id}.json`。
   抓到 0 主圖 = cookie 過期/被擋 → 彈窗提示重登。
4. **▶ 產出 Excel** → `batch_pipeline2.run_batch_two_tier(products=勾選的)`（= `batch2`，Claude
   文案+變體+影片 → 合併蝦皮二階 Excel）。缺 JSON / 無分類的編號會先彈窗提醒。
5. **📁 開素材夾** → 開 `output/上架素材/`（影片+尺寸表，蝦皮 Excel 無影片欄，手動補）。

執行緒模型同 launcher：worker thread 跑 `asyncio.new_event_loop()`，`root.after(0,…)` 回主緒更新 UI。
深色模式配色沿用 launcher（`tk_setPalette` + 每 widget 明確 bg/fg，避免 macOS 撞色隱形）。

## 抓取流程（兩條路，2026-07 更新）
**路 A（Chrome MCP 手動注入，半自動）** 與 **路 B（Playwright+cookie，GUI 全自動）** 選其一，
產出 JSON schema 完全一致，下游（images / batch2 / generate2）不用改。

路 B（GUI「🔍 抓取」＝ `scraper/playwright_scraper.py`，#S066 去風險驗證通過）：
帶 `config/cookies.json` 登入 cookie + stealth（改 `navigator.webdriver`/UA/locale/timezone）
用 Playwright 抓 detail 頁，**未被反爬擋**——推翻 #S064「Playwright 被 1688 擋」的舊結論
（當時的差別是**沒帶登入 cookie**）。主圖抓 JS 的 `offerImgList`（完整 9 張，非只 DOM 5 張縮圖）。
⚠️ `EXTRACT_JS`（此檔）與 `extract_1688.js` 是兩份平行實作、同一套選擇器，1688 改版時兩邊都要改。

路 A（Chrome MCP 手動注入）：不靠 Playwright、直接在「已登入的真實 Chrome」注入 JS，
最保險（連 stealth 都不必），但每商品要手動注入一次。步驟：
1.（一次性）Chrome 設定把 `detail.1688.com` 的「自動下載」設為允許
   （`chrome://settings/content/automaticDownloads`），否則 Blob 下載會被擋。
2. 在已登入的 Chrome 開商品頁，透過 Chrome MCP 注入 `scraper/extract_1688.js`
   → 抽 DOM（主圖/SKU 色卡/細節圖）→ 下載 `{item_id}.json` 到 ~/Downloads。
3. `python main.py images --ingest-downloads` → 搬進 `output/` 並下載所有圖片。

抓取選擇器（寫在 `extract_1688.js`，1688 改版時改這裡）：
- 主圖：JS 狀態的 `offerImgList`（遞迴找 window）→ 去重取原圖；找不到才退回 `.od-gallery-list img`。
  ⚠️ DOM 只 render 前幾張縮圖（P-a1 只 5 張），`offerImgList` 才是完整 9 張——**別只抓 DOM**。
- 第一軸（顏色/款式）：`.sku-filter-button`（圖在 `img`、名稱在 `.label-name`）
- 第二軸（尺碼）：商品屬性表 `尺码` 列（Ant Design `.ant-table-tbody`）
- 商品屬性：`.ant-table-tbody` 整張表 → `attributes` dict（餵文案規格欄：版型/材質/厚薄/彈力）
- 單價/各尺碼庫存：買區「尺碼 ¥價 库存N件」列 → `price_cny` + `size_stock`
- 細節圖：`window.offer_details.content`（描述 HTML 內的 `<img>`）
- 原圖還原：砍掉圖片 URL 第一個副檔名之後的 CDN 後綴（`_.webp`/`_sum.jpg`/`_800x800`）

⚠️ 1688 商品常是兩軸（顏色 × 尺碼）。第一軸是色卡按鈕、第二軸尺碼在屬性表/買區，
兩者來源不同，抓取要分別處理（曾只抓到顏色、漏掉尺碼）。

為什麼不用本機 server / 剪貼簿回傳：1688 的 CSP 擋掉對 localhost 的 fetch；
注入的 JS 無 user activation 寫不了剪貼簿；MCP 回傳字串 ~1000 字會截斷。
Blob 下載是唯一穩定把 JSON 落地的方式。

## 圖片兩條路線（GUI 每支勾選 ✨GPT / 不勾＝1688）
- **1688 直用（預設）**：Excel 圖片欄直接填 1688 原圖 URL（免圖床）。
- **✨GPT 生圖**：設計規範全在 `config/design_engine/*.md`（Edwin 維護，現為單一
  `JOYSLU_LADY_DESIGN_ENGINE.md` V1.0 宣告式規則），Claude 只「讀 md → 收圖 → 呼叫 API」不加工。
  `gpt_image_generator.generate_cover`：讀 md + 商品圖(main) + 1688 參考(detail) + 板娘(`persona/`)
  + 對手場景(`reference/`) → gpt-image-1 生圖 → `image_host.upload_images` 上 Supabase 圖床 → URL 塞 Excel。
  `_normalize` 先把圖轉 RGB PNG（避免舊照片 CMYK 被 API 擋）。GPT 路線在 `batch_pipeline2._gpt_images_for`。
- **⚠️ #S069 待接：正式引擎改 Responses API（gpt-5.5 導演 + image_generation 工具）+ 對話串接**
  （`previous_response_id`）——實測完勝 images.edit（文字全繁體、GPT 自主規劃整套）。原型在
  `scratch_listing.py`（+ `scratch_pure9/responses9.py`），尚未接進 `gpt_image_generator`。詳見全域踩坑筆記。
- **GPT 圖策略**（Edwin 定案）：實拍（學對手乾淨現貨、無字→零錯字）+ AI 賣點排版（補對手沒有的解說）拉差距。

## ★圖片正線：1688 圖轉蝦皮 1:1 繁體版（2026-07-09 #S070 定案，取代「AI 重畫」）
不讓 AI 重生成商品（會失真、布料變絲滑），改「**拿 1688 真實細節圖 → 逐張轉成蝦皮 1:1 繁體版**」＝最不失真。
原型 `scratch_transform.py`（per-image：`instructions`=保留原圖的英文 system prompt + md spec + 單張圖 → Responses API `image_generation` 工具）。**尚未接進 pipeline**（`scratch_transform_batch.py` 是多商品批次原型）。
- **定案配置**：畫圖模型 `gpt-image-1.5`、品質 `low`、設計規範 `JOYSLU_LADY_DESIGN_ENGINE.md`＝「轉蝦皮版 V2」（保留原圖、smart-crop 裁背景+outpaint 延伸讓人物填滿 82-88%、禁止整張縮小加白邊、簡轉繁、刪英文）。
- **只轉「全身乾淨模特圖」**（人工看 contact sheet 分類 detail 檔挑全身★★★★+）；純文字/尺碼/面料面板**別餵 AI**（會爛字）→ 尺碼表用 `size_chart_maker.make_size_chart` 程式做繁體版（數據從該商品尺碼細節圖人工讀）。
- **成本**：gpt-image-1.5 low 每張 ~$0.009、每商品 ~$0.10（含 gpt-5.5 導演）。**費率校正**：每張 = 固定 token(1024²：low272/med1056/high4160) × 模型 output 費率（img-1 $40 / img-1.5 $32 / mini $8 每 1M）。mini-low 便宜但保真差（灰變藍、改姿勢）→ 不用。詳見全域踩坑 #S070。
- **✅ Supabase URL 塞蝦皮已實測可行**（HTTP 200 公開可讀，蝦皮抓得到）。轉換圖上圖床 → URL 覆蓋進 Excel 商品圖片欄（S 封面 + T~AA）：把 `batch_pipeline2._gpt_images_for` monkeypatch 成「上傳既有轉換圖」+ 各商品 `route='gpt'`、`reuse_content=True` 即可重建 Excel。
- **影片**：`video_maker.make_product_video` 合成轉換圖幻燈片；**1688 原始影片**＝抓 `<video>` 元素 src（`playwright_scraper`/`extract_1688.js` 已補 `video_url` 抽取）→ 下載 `cloud.video.taobao.com` mp4 ⚠️**不能帶 `Referer:1688` header**（CDN 回 0 byte），只帶 User-Agent。

## ★走 A：全自動圖片 pipeline（視覺分類，2026-07-09 #S070，43+13 支實跑）
取代「人工看 contact sheet 挑圖 + 人工讀尺碼表」。兩支：
- **`scraper/auto_classify.py`**：`classify_details(item, subdir='detail')` 把細節圖做成 contact sheet → 一次 gpt-5.5 vision 呼叫 → `{fullbody:[stem], sizechart:stem}`（挑全身乾淨模特圖 + 找尺碼表）；`read_size_chart(item,stem)` 讀尺碼表 → `{headers,rows,weight_jin}`。分類器偏保守（寧缺）；體重(斤)常讀不到→尺碼表體重註記可選。
- **`scratch_auto_pipeline.py`**（`AILIST`/`IDSFILE` 環境變數指定名單）：分類→轉換(3緒+429退避)→尺碼表(斤÷2→kg)。**轉換務必 ≤3 併發+退避**（OpenAI 圖生 6 併發會 429）。存 `output/_auto_classify.json`。
- **全批流程**：抓取 → 下載圖(`download_product_images_from_json` dest_dir=`output/{item}/images` 要含 /images！) → auto_pipeline → batch2(monkeypatch `_gpt_images_for` 上傳轉換圖) → 影片+打包。
- **踩坑**：① 分頁 gid 要用 `/export?format=csv&gid=` 端點（gviz 不吃 gid、回預設頁）；② 少數商品 1688 無細節圖(detail=0)→退用 main 圖(帶簡體側欄，AI 常沒翻繁)；③ 安全裤/鲨鱼裤類全身模特圖少、分類器挑得少；④ Anthropic 額度用完 batch2 會「文案失敗」靜默跳過→ console.anthropic.com 儲值(API≠claude.ai 訂閱)。

## ★尺碼「公斤 vs 斤」三軌分離（2026-07-09 #S070，血淚，務必分清）
**買家看公斤、1688 對照用斤、貨號用純字母**，三者不同用途不可混：
1. **買家選項（規格選項2 L欄）＝公斤**：copywriter 源頭修（prompt 規定「體重一律 kg、斤÷2、絕不出現斤」）+ `build_variants._label_kg`（抽 kg 或斤÷2）+ `copywriter.scrub_jin`（詳情內文掃斤）三層都改。
2. **商品選項貨號尺碼（O欄 join key）＝純字母**：`build_variants._clean_size_key` 把「M【80-100斤】」清成「M」（貨號只是識別碼、不需含斤；蝦皮匯出欄33 ↔ 訂貨表兩邊一致即可）。
3. **⚠️ 訂貨表「規格二」(給 cart_adder 在 1688 選規格)＝斤，必須是 1688 原文**（如 `M【80-100斤】`/`S（80~95斤）`）：**來自抓取 JSON 的原始 `sizes`，公斤修正完全沒動它**。建訂貨表時規格二**務必用 JSON 原始 sizes 對回**（別用清過的 key 硬湊，否則像 P14AE12「M【80-100斤】」對不到）。

## 已遷出子系統（詳細文件見各自 repo）
以下曾在本 repo、#S130/S134 已整包遷出，詳細設計/踩坑見對應 repo 的 CLAUDE.md：
- **②訂貨 / ③金流·到貨對帳（含常駐 reconcile_daemon）** → `1688-order`（每日訂貨小幫手 order_gui + 背景對帳 daemon）。
- **④ Kkren（巧巧郎）到貨抓取** → `kkren-sync`。
- **⑤ 蝦皮後台數據抓取 + AI 店長分析層** → `shopee-analytics`。
（本 repo 只保留「1688→蝦皮上架」本業：爬取→AI 文案→蝦皮 Excel + 商品資產包。）

## 環境變數
- `ECOMMERCE_DESIGN_DIR` — 生圖設計規範資料夾。#S130：`scraper/{gpt_image_generator,auto_classify,image_host,video_maker,size_chart_maker}.py` 已改為 re-export shim → 真碼在 `ecommerce-media` 套件。gpt_image_generator shim 會自動把此 env 指回 `config/design_engine`（品牌政策留本 repo），一般不用手動設。
- `ANTHROPIC_API_KEY` — Claude API key（文案引擎 copywriter.py + 分析層 AI 店長顧問 advisor.py）
- `OPENAI_API_KEY` — GPT 生圖（gpt-image-1.5）
- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`（`sb_secret_…`）/ `SUPABASE_BUCKET`（預設 `joyslu-images`）
  — GPT 生圖圖床（Supabase Storage public bucket；只 GPT 路線用）。service key 是機密，勿 commit。
- `GEMINI_API_KEY` — Google Gemini API key（舊文案/生圖，保留備用）
（註：已遷出子系統的 env — RECONCILE_SHEET_ID / KKREN_SHEET_ID / SHOPEE_ANALYTICS_SHEET_ID_* / SHOPEE_DASHBOARD_SHEET_ID — 隨 ②③④⑤ 移到 1688-order / kkren-sync / shopee-analytics，見各 repo。）

## 顏色/尺寸選項政策（color_policy.py + batch 兩層篩選）
蝦皮單商品上限 **100 SKU**。SKU = 第一軸 × 尺碼。原則（Edwin 拍板）：
- **尺寸全留**（尺寸不對無法替換，是硬需求）。
- **身高款/版型（常規/高個子/小個子）＝當尺寸看，全留**（也是合身維度）。第一軸常是
  「顏色 × 身高款」綁在一起（如「黑色-常規款」「黑色-高個子」），`base_color()` 剝掉身高款
  token 取純底色，**同底色的身高款整組綁著留或整組砍，不拆散**（否則會挑出「4色常規+1黑高個子」亂配）。
- **只砍顏色**：`select_first_axis()` 把底色挑成**熱門色 ≤5**（求色系分散），100 保底。
  熱門保留色（Edwin 拍板 11 個）：黑/白/灰/米/咖啡/大地/藏青/卡其/軍綠/牛仔藍/深藍。
  判斷靠**修飾詞**（`hot_color_tier`）：**藍預設留**（丹寧/復古/牛仔/深/藏青…都是藍，頂多兩三個），
  只砍**亮藍**（天藍/湖藍/寶藍/亮藍/淺藍/釉藍/電光/克萊因）；**綠預設砍**，只留**暗綠**（軍綠/墨綠/橄欖）；
  粉/黃/紫/橙/紅一律砍。0 熱門色 → flag 人工。
- **兩層篩選**：第一層＝Edwin 在名單「款式」欄的自然語言備註（如「不要加絨的冬天款」），由
  **copywriter 的 Claude 呼叫**回傳 `style_kept`（保留哪些第一軸選項）；第二層＝上面的中性色政策。
  名單「款式」欄空白/「全款式」= 第一層全留。手動 `entry["colors"]` 指定則完全覆寫、不套政策。

## 文案引擎（copywriter.py）
讀 `config/sop/` 的女裝 SOP（03f + 母規範 v2.4）→ Claude 生：商品簡稱（繁體台灣用語、無中國用語）、
蝦皮標題、8 區塊詳情、顏色簡繁對照、尺碼標籤、flags。`build_variants()` 用程式拼蝦皮二階規格選項名
（`編號_簡稱_顏色` / 尺碼），確保精準不交給 LLM。大 SOP 走 Anthropic prompt cache。

## ★商品資產包（product_card.py + master_reader.py，2026-07-26 #S103）
標題/詳情**不系統化生成**（回網頁版 Chat 討論+二調）；系統只負責「記住商品」＝**每個商品一個
可累積資料夾**放雲端硬碟（Chat 連接器直接讀）。`generate_asset_packs()` 產：
```
{賣場}/商品資產/{編號}/
├── 商品卡.md      ← 100% 純廠商固定事實（一基本 二特徵 三選項規格 四基礎數據；動態編號）
├── 商品賣點.json  ← vision 讀詳情圖抓的賣點（可累積編輯）
├── 基礎圖/(main/detail/sku) 優化圖/ 影片/ raw.json
```
- **主表驅動（`--master`）**：`master_reader.read_master()` 讀【Nail】1-1 商品主表「商品表」分頁
  → 資料夾名＝**主表商品編號**（AAS1，跨訂貨/庫存一致）、廠商用主表（抓取常抓不到店名）。
  SA 憑證自動找（env `ORDER_SHEET_SA_JSON` / settings / `~/OneDrive/文件/inventory-sync-*.json`）。
- **軸命名通用化**：軸標題跟 1688 實際 attribute 走（甲油膠→顏色、光療燈→規格）；`_axis2_title`
  只有像尺碼（S/M/L/斤）才叫「尺碼」，否則「規格/選項」——修美甲燈 52 型號被誤標尺碼。
- **賣點解析（`--analyze`）**：`auto_classify.extract_highlights()` gpt-5.5 vision 讀詳情圖 →
  條列廠商印在圖上的賣點/規格（屬性表抓不到的），過濾出貨備註/虛詞/重複。需 `OPENAI_API_KEY`+圖。
- **繁體**：opencc `s2tw`（純字形，**不用 s2twp**——會誤換「項目→專案」「类型→型別」慣用詞）。
- **售價/分類/文案**＝我方決策/會變動 → **不寫進商品卡**，從主表核對（Edwin 定調：卡只放固定事實）。
- CLI：`product-cards --shop nail --master --flat --download-media --analyze --out-base "G:\…\商品資產"`
  （`--flat`＝雲端已按賣場分夾時不再加 nail/ 子夾）。抓取無 cookie 也常成功（scrape_many）。
- **一鍵同步（正線運轉，`asset_sync.py` + `sync-assets` CLI + `run_sync_assets_windows.bat` 雙擊）**：
  `要產`(checkbox)＋`資產包狀態`(✓) 兩欄。Edwin 勾要跑的 → 觸發：讀勾選 →
  抓取 → 產資產包寫雲端 → 回寫 `資產包狀態=✓`＋清 `要產`。**增量**只跑勾的/未完成的、被擋跳過。
  - **⚠️ 2026-07-29 欄位搬家**：Edwin 把 `要產`/`資產包狀態` 從「商品表」搬到「**蝦皮處理狀態**」分頁。
    `open_for_sync` 改為：商品資訊(編號/網址/廠商/品名)讀「商品表」、勾選/完成狀態讀寫「蝦皮處理狀態」
    （以**商品編號 join**、回寫寫該分頁）。**覆蓋範圍變小**：只有「蝦皮處理狀態」有列的編號（＝已上架子集）
    才能被勾選驅動；商品表有但該分頁沒有的（未上架）暫無法勾。**同編號多變體**（如 H-c30 基本+高腰）
    共用同一個勾選、會產各自 item_id 的資產包。
  - **⚠️ 必配套改 Apps Script**：「蝦皮處理狀態」是 `status_sync_addon.gs` 的 `syncStatusTab()` 以商品編號
    重建的分頁。已把保留區從 D:K 擴到 **D:N**（L 蝦皮折扣/M 資產包狀態/N 要產一起按編號帶回、N 重補勾選框），
    否則重建時勾選會錯位到別的商品。**這是 repo 內的原始碼，改完要重新貼進雲端綁定的 Apps Script 才生效。**
    ⚠️ Lady/Baby 綁定的 `{lady,baby}_master_Code.gs` 也各有一份 `syncStatusTab`，Nail 改了要同步（Lady 已於 2026-07-30 補 D:N；Baby 仍 D:K 待補）。
  - **⚠️ 2026-07-30 跨賣場**：`open_for_sync(sa_json, shop="nail")` 加 `shop` 參數＋`SHOP_SHEETS`(nail/lady/baby)，
    按 shop 換主表 sheet_id（三家「商品表」gid 皆同 `1584079803`）；`asset_sync.sync_assets(shop=…)` 已帶下去。
    原本寫死 Nail → 現 `sync-assets --shop lady` 真的讀 Lady（實測 Lady 讀到 249 商品、要產/資產包狀態欄對得上）。
  `--all`＝跑所有未完成、`--no-analyze`＝省 vision。雲端根＝`settings.ASSET_CLOUD_BASE`（env 覆蓋）。
  資料夾名＝`{編號}_{品名}`（如 `AAS1_AS_黑瓶功能膠`，編號給 AI、品名給人認）。要在 Edwin 機器跑
  （Playwright/SA/OPENAI_API_KEY/掛好的雲端硬碟）。

## 爬取方式說明
1688 反爬嚴格（Playwright 即使用 channel="chrome" 仍被偵測），目前實際爬取是透過 Claude in Chrome MCP 在用戶已登入的 Chrome 中執行 JS 提取 DOM。Playwright 相關程式碼保留作為備用。

## AI 生成規則
蝦皮商品描述禁止：產地、出貨速度字眼、導外聯繫、站外交易引導、其他平台名稱、絕對化用語、醫療宣稱。詳見 `gemini_generator.py` 的 SHOPEE_SYSTEM_PROMPT（與 `ai_generator.py` 同規則）。

## 蝦皮大量上架 Excel 黃金規則（2026-06-30 實測過審，血淚換來，務必照做）
產檔邏輯在 `shopee_excel.py` 的 `generate_two_tier_excel` / `build_two_tier_rows` / `_insert_data_rows`。
對照「已過審的範本」逐欄比對得出（花花 2026-05-22 檔），任一條錯都會被蝦皮擋。

**檔案結構（最關鍵，錯了會「版本不同/請下載最新模板」）：**
1. **用蝦皮當下給的最新模板**：模板第 2 列藏版本 hash（`basic | <hash>`），蝦皮比對它。
   不同次下載 hash 不同；產檔時 `config/shopee_template.xlsx` 要是使用者該次下載的那份。
2. **只「插入」資料列，模板其餘 100% 原封不動**：表頭、sharedStrings、所有 sheet 一個 byte 都不能改。
   重建表頭或 rebuild sharedStrings 會動到 hash → 被擋。`_insert_data_rows` 只在 `</sheetData>` 前塞列、
   sharedStrings 只「追加」新字串不動既有索引。
3. **資料從第 7 列開始**（前 6 列是表頭，第 6 列是提示行也要保留）。放第 6 列會吃到提示行。
4. **儲存格用 sharedStrings（`t="s"`），不可用 inlineStr**（蝦皮解析器只吃 sharedStrings）。
5. **欄位用第 0 列內部 key 動態對應**（`ps_category`/`et_title_*`/`channel_id.*`），不可寫死欄號——
   模板版本會在 43 欄/44 欄、物流頻道組合間變動，寫死必跑版（`build_col_map`）。

**欄位值（錯了會「型號與變體不匹配」或「格式錯誤」）：**
6. **數字欄一律寫「文字字串」**：蝦皮用 Go `ParseUint` 讀，數字儲存格會被讀成 `"1.0"` → 失敗。
   價格/庫存/識別碼/最低購買量/備貨天數存成 `"998"`、`"1"`、`"9"`。
7. **商品規格識別碼**（`et_title_variation_integration_no`）：同商品所有列填**同一整數**（如 `1`）——
   這是把多列歸成「一個商品」的鑰匙。只填第一列 → 每個 SKU 變成獨立商品。
8. **規格名稱1/2（顏色/尺碼）每列都填**；規格選項1/2 每列填各自的值。
   ⚠️ **規格選項名稱（1 與 2）長度限 1~20 字**（超過蝦皮擋「層級選項名稱長度必須介於1到20個字符之間」）。
   故規格選項1 = `簡稱_顏色`（**砍編號**才塞得下）；`_clip20()` 超長時退成純顏色。
9. **主商品貨號（`ps_sku_parent_short`）填編號**（商品層識別；#S066 實測「填編號+型號留空」合法）。
10. **危險物品（`ps_dangerous_goods`）留空**（= 預設否；不要填 Yes/No/是/否）。
11. **商品選項貨號（`ps_sku_short`，O 欄）＝`編號_顏色_尺碼`**（各司其職：買家選項不顯貨號、貨號不顯商品名，
    供庫存系統解析到 SKU 層）。⚠️ **血淚風險**：#S066 實測「型號每 SKU 唯一填值」曾被判「型號與變體不匹配」
    資料靜默不進，故一度留空；此格式 per-SKU 唯一且含中文屬同風險模式——**Edwin 要求此設計，務必先測 1~2 筆
    確認資料真的有進、再全批**（若掉：退回留空、改用主貨號+規格選項辨識）。
12. **物流**：啟用的頻道填 `開啟`，停用的**留空**（不必填「關閉」）；每列都填。
13. **分類（`ps_category`）填分類 ID（數字，如 `100358` 女生衣著/長褲）**，不是文字。
    ID 在模板「較長備貨天數範圍」sheet 查（`et_title_category_name`/`et_title_category_id`）。
14. **圖片**用 https 網址（1688 原圖即可，選填）；**品牌**基本模板沒欄位，UI 選 JoysLu（編號 6379087 通用）。

**二階規格命名（各司其職，皆 ≤20 字）：**
- 規格選項1（買家看，I 欄）= `簡稱_顏色`（如 `亞麻闊腿褲_黑色 / 常規款`；不含編號，塞得下 20 字）
- 規格選項2（買家看，L 欄）= 尺碼（如 `S（40-47.5 kg）`）
- 商品選項貨號（O 欄）= `編號_顏色_尺碼`（如 `P14AE1_黑色 / 常規款_S`；供庫存系統解析）
`copywriter.build_variants` 拼規格選項1（帶 color/size 供貨號），`shopee_excel.build_two_tier_rows` 拼貨號 + `_clip20`。

## 圖片後製介面
`downloader.py` 中的 `download_product_images_from_json()` 預留了 TODO 註解，之後接入圖片後製 pipeline。

## 🧠 知識庫整合（ai-memory CLI）

本機已安裝 Edwin 的顧問知識庫 CLI（`/Users/weilu/projects/ai-memory-tools`），可在任何專案目錄使用。

### Session 開始時（建議）
```bash
ai-memory sync
```
產出 `./AI-Memory/recent-knowledge.md`，內含近 14 天的「核心 + 置頂」知識，Claude Code 可作為背景參考。

### 開發中按需查詢
```bash
ai-memory query --tags "庫存,inventory"
ai-memory query --category "經營原則"
```

### Session 結束時（可選，重要結論才存）
```bash
echo "今天決定 XXX，原因是 YYY..." > /tmp/session.md
ai-memory save -f /tmp/session.md -i core -t "決策,X"
```

### 列出與統計
```bash
ai-memory list           # 最近 10 筆
ai-memory stats          # 知識庫統計
```

完整文件：`/Users/weilu/projects/ai-memory-tools/README.md`
