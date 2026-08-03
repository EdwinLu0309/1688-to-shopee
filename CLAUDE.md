# 1688-to-shopee

## 專案簡介
1688 商品資訊爬取 → AI 生成蝦皮文案 → 蝦皮批次上架 Excel 自動產生。

## ⚠️ 已遷出的子系統（#S130 清理批次完成）
六子系統拆解收尾，以下已移到獨立 repo、**本 repo 舊碼已移除**（下方詳細章節僅為歷史參考）：
- **⑤ 蝦皮後台分析** → `shopee-analytics` repo（原 `scraper/shopee_analytics/` + main.py `shopee-*`/`order-basket` 命令已刪；排程 plist 已指新 repo；`docs/shopee_analytics_api.md` 帶去該 repo）。
- **④ Kkren 到貨** → `kkren-sync` repo（原 `scraper/ordering/kkren_{scraper,pipeline}.py` + main.py `kkren-refresh` 已刪）。**③ `reconcile_daemon` 的到貨口已解焊**：改 subprocess 呼叫 `kkren-sync` 的 `kkren-refresh --commit`（跑它自己的 venv + cookie-hub token）。
- **① 1688 抓取** → `ecommerce-sources.alibaba1688`；**⑥ 素材** → `ecommerce-media`（5 模組，本 repo 為 re-export shim）；**讀表** → `ecommerce-sources.gsheet`。
- 尚未遷出：**②③ 訂貨/對帳**（`scraper/ordering/` 其餘 + 三個 GUI）仍在本 repo。

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
├── order_gui.py               # ★每日訂貨 GUI（獨立，不動 gui.py）：匯入蝦皮匯出→彙總→下單→核對
├── reconcile_gui.py           # ★1688 訂單刷新 GUI（獨立）：抓 1688 待付款訂單→覆蓋金流核對表 1688_DB
├── run_mac.command            # Mac 啟動 GUI（優先 .venv/bin/python，Tk 9.0 深色正常）
├── run_windows.bat            # Windows 啟動 GUI
├── run_order_mac.command      # Mac 啟動訂貨 GUI（order_gui.py）
├── run_order_windows.bat      # Windows 啟動訂貨 GUI
├── run_reconcile_mac.command  # Mac 啟動金流核對 GUI（reconcile_gui.py）
├── run_reconcile_windows.bat  # Windows 啟動金流核對 GUI
├── main.py                    # CLI 入口（login/scrape/generate/batch/order-*/reconcile-refresh/kkren-refresh/shopee-login/shopee-collect/shopee-collect-daily）
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
│   └── ordering/              # ★每日訂貨系統套件
│       ├── models.py          # OrderLine/MasterEntry/SummaryRow/OrderItem
│       ├── shopee_export.py   # 解密+讀蝦皮 toship 匯出 → OrderLine
│       ├── order_sheet.py     # gspread 三分頁讀寫（主檔/明細/彙總 + SA）
│       ├── pipeline.py        # 匯入→join→明細+彙總→今日總金額（dry-run 預設）
│       ├── cart_order.py      # 彙總→OrderItem→cart_adder 加購/cart_verifier 核對
│       ├── cart_adder.py      # vendored 自 1688-order（1688 改版兩邊同步）
│       ├── cart_verifier.py   # vendored 自 1688-order
│       ├── pending_scraper.py # ★金流核對：頁內 mtop 抓 1688 待付款訂單 → OrderRecord/1688_DB 26欄
│       ├── reconcile_db.py    # ★覆蓋金流核對表 1688_DB 分頁（gspread SA）；arrival=50欄到貨版
│       ├── reconcile_pipeline.py # ★刷新流程：抓訂單→(可選)覆蓋 1688_DB（dry-run 預設）
│       ├── reconcile_daemon.py # ★常駐監聽 daemon：輪詢各表控制分頁勾選→抓 1688→直寫該表 1688_DB
│       ├── kkren_scraper.py   # ★抓 Kkren(巧巧郎)已出貨包裹（httpx+Bearer token）→ Kkren_Data 7欄
│       └── kkren_pipeline.py  # ★Kkren 刷新：抓已出貨→去重 append 中繼表 Kkren_Data（dry-run 預設）
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

## AI 名單怎麼從 Google Sheet 落地成 CSV（私有表；兩條 cookie 來源）
名單是**私有** Google Sheet（`AI_LIST_SHEET_ID`，見 settings.py），公開匯出 URL 會 401，
只有帶登入 cookie 的 httpx 打 `/gviz/tq?tqx=out:csv&gid=<gid>` 才讀得到 → 存 `input/lady_ai_list.csv`。
入口：GUI「⬇️ 更新名單」/ CLI `python main.py fetch-list`。`sheet_fetcher._cookie_sources`
依序試兩條來源，第一個抓到合法 CSV 的就用：

1. **Playwright 登入的 session（跨平台，Windows 主力）**：`scraper/google_login.py`
   `save_google_session()` 用**真實 Chrome**（`channel="chrome"`，Google 較不擋自動化）開瀏覽器，
   使用者登入一次 → 拿 context.request 試抓 gviz，抓到合法 CSV 才算登入成功 → 存
   `config/google_cookies.json`（gitignored）。之後 `load_saved_cookies()` 帶進 httpx 重複用。
   入口：GUI「🔑 Google 登入」/ CLI `python main.py google-login`。session 過期就再登一次。
2. **收割日常 Chrome 的 Google cookie（macOS 免登入零點擊）**：`scraper/chrome_cookies.py`
   `get_cookies("google.com", profile)`。macOS：`security` 取 "Chrome Safe Storage" →
   PBKDF2-SHA1(saltysalt,1003) → AES-CBC v10。Windows：`Local State` 的 DPAPI 金鑰 →
   AES-256-GCM 解 v10/v11。逐一 Chrome 設定檔試。移植自 listing-optimization-tool 的
   `grab_session.py`（#S065）。

⚠️ **Windows Chrome 的 cookie 幾乎全是 App-Bound Encryption（v20）**（Chrome 127+），金鑰再被
Chrome 服務包一層，純 DPAPI 解不開（要 SYSTEM 權限 / IElevator COM），`chrome_cookies` 遇 v20
**直接跳過** → Windows 上來源 2 通常收不到料，**一律走來源 1（Google 登入）**。macOS 仍是零點擊。
⚠️ Windows 主控台預設 cp950，輸出 ✓✗/中文會 UnicodeEncodeError → `config/settings.py` 開頭
把 stdout/stderr `reconfigure(encoding="utf-8")`（main.py 與 gui.py 都早期匯入 settings）。
⚠️ 讀舊本機 CSV = 讀到舊資料：實際踩過本機檔停在 2 商品舊版、線上表其實已 48 商品。
（備用：路 A＝登入 Chrome 開試算表分頁後同源 fetch gviz → Blob 下載到 ~/Downloads，Chrome MCP
`javascript_tool` 直接回傳 CSV 會被「Cookie/query string data」安全過濾擋掉，只能走 Blob。）

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

## ★訂貨系統（3 分頁 Google Sheet + 獨立下單 GUI，2026-07-09 #S070／Phase A+B 已建）
每天 200-300 預購商品要下單，用一張 Google Sheet（SA `inventory-sync@inventory-sync-493112.iam.gserviceaccount.com` 需被分享為編輯者；SA 無 Drive 容量不能自建檔，要 Edwin 建空白表再分享）。**三分頁**：
1. **`1_訂貨主檔`**（靜態、隨上架累加）：`商品選項貨號 | 編號 | 商品簡稱 | 1688網址 | 規格一(1688原色) | 規格二(1688尺碼) | 進貨¥`。
   - **join key＝商品選項貨號**（= 蝦皮 O 欄 `編號_顏色（身高款）_尺碼`，如 `P14AE1_黑色（常規款）_S`；已實測蝦皮會吃、匯出欄33 對得上）。
   - **規格一/二 = 1688 原始規格**（cart_adder 選規格用）：規格一取 `build_variants` 的 `src_1688`（如 `（升级面料）-黑色-常规款`，**實測與 1688 頁面 `.sku-filter-button .label-name` 逐字相同**）；規格二取 1688 原尺碼字串（如 `S（80~95斤）`，**格式是否與頁面尺碼列逐字相同待 cart_adder 首次實跑驗**）。
2. **`2_每日訂購彙總`**（訂貨依據，餵 cart_adder）：`日期 | 商品選項貨號 | … | 總數量 | 進貨¥ | 成本小計 | 下單狀態 | 下單時間`。**由分頁3 程式自動聚合，不手填。**
3. **`3_訂單明細`**（出貨依據，按訂單編號）：`日期 | 訂單編號 | 買家帳號 | 商品選項貨號 | 編號 | 數量 | 出貨狀態`。一列一張蝦皮訂單明細（解「同 SKU 多買家」的一對多：留成多列不塞一格）。到貨後篩 SKU → 知道寄給哪幾張單。
- **蝦皮匯出**：`Order.toship.YYYYMMDD_*.xlsx` 有密碼（msoffcrypto 解），關鍵欄：欄33 商品選項貨號、欄34 數量、欄0 訂單編號、欄5 買家帳號、欄27 商品選項名稱。
- **資料流**：蝦皮匯出 → append 分頁3（原始明細）→ 同 SKU 聚合寫分頁2（總量+成本）→ 按下單 cart_adder 跑 → 回寫分頁2 狀態。
- **下單顆粒度待驗**：分頁2 記到 SKU（色×尺碼）；若 1688 是單軸（只有色-款式無尺碼軸，本商品尺碼列靜態探測不到、待實測）→ 餵 cart_adder 前要再聚合到「色-款式」層。
- **下單工具（獨立簡易版，已建於 `scraper/ordering/`）**：資料骨幹（Phase A）+ 下單整合（Phase B）都已寫好、Sheet 讀寫實測過；只差**首次實跑下單驗規格二尺碼格式**（要真的有預購訂單 + Edwin 開瀏覽器）。
  - **套件 `scraper/ordering/`**：
    - `shopee_export.py`：msoffcrypto 解密 toship 匯出 + calamine 讀，抽欄 0/5/25/27/33/34（訂單編號/買家/商品名/選項名/貨號/數量），含表頭校驗防跑位。
    - `order_sheet.py`：gspread + inventory-sync SA。`load_master`（分頁1）/`append_details`（分頁3，去重 by 訂單編號+貨號）/`upsert_summary`（分頁2，clear+rewrite 某日 idempotent）/`update_order_status`（回寫分頁2）。
    - `pipeline.py`：`import_orders`（匯出→join 主檔過濾預購品→建明細→聚合彙總→算今日總金額）。**預設 dry-run，`commit=True` 才寫 live sheet**。純函式 `build_import` 好測。
    - `cart_order.py`：`build_order_items`（彙總 join 主檔補 1688 網址）→ `place_orders`（驅動 vendored `cart_adder`，按 url 分組加購）→ 回寫狀態；`verify_cart` 驅動 `cart_verifier`。`run_place_orders` 只跑「下單狀態空」的列（防重複下單）。
    - `cart_adder.py`/`cart_verifier.py`：**vendored 自 `~/projects/1688-order/order/`**（只改 `OrderItem` import 來源）。⚠️ 1688 改版時兩專案的選擇器都要同步。
  - **CLI**：`python main.py order-import <toship.xlsx> -P <密碼> [-d 日期] [--commit]` / `order-place [-d 日期]` / `order-verify [-d 日期]`。
  - **GUI**：`order_gui.py`（獨立，不動主 `gui.py`）＝選匯出檔+密碼+日期 → 📥匯入預覽(dry-run 顯示彙總+總金額) → ✅寫入Sheet → 🛒下單 → 🔍核對。啟動：`run_order_mac.command` / `run_order_windows.bat`。
  - **下單 cookie**：用主 gui.py 的「🔑 登入 1688」產生的 `config/cookies.json`（cart_adder 直接吃）。
  - 進貨¥ 目前多數主檔列未填 → 成本小計顯示「無進貨¥」，Edwin 補 `1_訂貨主檔` G 欄即計入總金額。

## ★金流核對刷新（1688 訂單→1688_DB，2026-07-13 #S072，取代手動匯出報表）
解決「每次要用電腦開 1688 待付款→勾選→匯出訂單報表→丟資料夾→匯入 DB」太繁瑣、手機做不到、
且**廠商偷改價看不出來**的痛點。按一顆按鈕就把當下 1688 訂單撈進金流核對表。
- **目標表**：`【Nail】2-1. 進貨金額記錄_2026`（`RECONCILE_SHEET_ID`，settings.py；SA=inventory-sync 已有編輯權）。
  分頁 `1688_DB`（26 欄，＝1688 官方「訂單報表」匯出 xlsx 原樣）存訂單原始資料；各日期核對分頁
  （`0713` 等）靠 **`卖家公司名`（廠商）** VLOOKUP 帶入 `付款平台訂單編號/訂單費用/總金額/運費`。刷新只動
  `1688_DB`、不碰核對分頁。
- **抓取法（去風險定案）**：不刮脆弱的 shadow DOM（air.1688 訂單頁是 Lit q-table 虛擬滾動）、也不打
  簽章混淆的 mtop——而是 **Playwright 進頁後，在頁內用該站自己的 `lib.mtop` JS 呼叫訂單清單 API**（自動簽章、
  可翻頁）：`mtop.1688.trading.dataline.service` + `serviceId=OrderListDataLineService.buyerOrderList`，
  `param={"tradeStatus":"waitbuyerpay","page":N,"pageSize":100}` → `res.data.data.result`(JSON字串)
  → `{data:{data:[...訂單...],total,pages}}`。改版時改 `pending_scraper.py` 的 `CALL_JS`。
- **欄位對應**（⚠️ 金額單位是「分」÷100）：`idStr`→訂單編號、`sellerInfo.companyName`→卖家公司名（核對 key）、
  `sumProductPayment`→货品总价、`carriage`→运费、`sumPayment`→实付款、`gmtCreate`→订单创建时间（格式化 `Y/M/D`）、
  `orderEntries[]`→品項（productName/price/quantity/productNumber/sourceId=Offer ID/skuId）。折扣＝货总−实付。
  一訂單多列（首列填訂單級欄+首品項，後續列只填品項欄），比照官方報表格式。清單 API 的收貨地址/電話被遮罩→留空（核對用不到）。
- **日期篩選**：只留 `gmtCreate >= 核對日期`（預設今天）——今天下的訂貨表就核對今天(含)之後的訂單，不對到舊批。
- **合併累加語義**（2026-07-29 改，原純覆蓋）：重抓待付款訂單**合併**進 `1688_DB`——仍在待付款的訂單用新值覆蓋
  （廠商改價→實付款一起更新，這就是「看得出廠商改價」的關鍵），**這次沒抓到的訂單整組保留**。⚠️原因：Edwin 一批下很多單、
  逐筆核價，會先按付款結掉部分訂單再繼續核剩下的；已付款訂單離開「待付款」→ 純覆蓋會把它連訂單編號一起清掉，就無法出到
  2-2 到貨表核對（訂單編號對不上）。故改合併保留已付款訂單（純函式 `pending_scraper.merge_order_grid`，與到貨版共用；
  到貨版多做運單號回填）。⚠️**0 筆時防呆略過寫入**（避免無謂重寫）。
- **入口**：GUI `reconcile_gui.py`（獨立，不動 gui.py/order_gui.py）＝設核對日期→🔄刷新預覽(dry-run 顯示筆數/實付合計/廠商)
  →✅寫入 1688_DB。啟動 `run_reconcile_mac.command` / `run_reconcile_windows.bat`。
  CLI `python main.py reconcile-refresh [-d 日期] [-s 狀態] [--commit]`。cookie 用主 gui.py 的「🔑 登入 1688」產生的 `config/cookies.json`。
- **✅ 已實跑驗證**（#S084）：美甲帳號＝`jiaorong0826`（**非** joyslunailshop，那是服飾帳號）。抓 31 筆 7/13 真待付款、
  直接覆蓋 ① 的 `1688_DB`，0713 分頁活公式（`=XLOOKUP(廠商, '1688_DB'!D:D…)`）即時對上（阳东星慕 ¥579.31 與 1688 頁一致）。
  ⚠️ 折扣欄語義與 1688 原匯出可能略不同，但**实付款＝sumPayment 是權威值**、核對看它。

## ★ERP 式常駐監聽自動化（打勾→Mac 常駐→自動更新，2026-07-14 #S084）
Edwin 要「在雲端頁面點一下就自動更新」的 ERP 體驗（他 Mac 永遠開機，見全域記憶 [[mac-always-on-host]]）。
- **架構（去風險定案）＝輪詢式監聽 + 各表直寫**：`reconcile_daemon.py` 常駐輪詢各消費表的「🔄刷新控制」分頁勾選格
  （SA 每 20s 讀），看到打勾 → 抓 1688 → **直接覆蓋那張表自己的 `1688_DB`** → 清勾 + 回寫「狀態/最後更新」。
  日期分頁本來就活公式 XLOOKUP 本地 `1688_DB`，故直寫即時生效、**免 IMPORTRANGE 授權、免中央檔**。
  （原本規劃中央檔 ③【全】1688訂單資料 + IMPORTRANGE，但實測發現：① 各表 SA 都寫得進、② 金額/到貨抓不同狀態沒共用資料
  → 直寫各表更簡單，中央檔+IMPORTRANGE 棄用；IMPORTRANGE 首連需人工點「允許存取」是它的痛點。）
- **config 驅動多口去重**：`JOBS`＝帳號 cookie + 抓取 + 寫哪張表 1688_DB + 觸發口清單。多口同 job（金額表+到貨表都要更新）
  任一打勾只跑一次。新增賣場＝加一列 JOB + 那張表加控制分頁（`setup` 自動建勾選框），不改邏輯、不多開 daemon。
- **多帳號 cookie 分離**：金流核對＝美甲帳號 `config/cookies_nail.json`（reconcile_gui「🔑登入美甲帳號」按鈕產）；
  Lady 上架/訂貨仍用 `config/cookies.json`。兩邊不再互相蓋掉。⚠️ 踩坑：Edwin 以為登入美甲了，但 gui.py 登入存到
  cookies.json 而非 cookies_nail.json，且首次登入沒存成功（mtime 沒變）→ 一直抓到服飾帳號 0 筆。
- **常駐＝LaunchAgent**：`config/com.joyslu.reconcile-daemon.plist`（開機自啟、KeepAlive、免終端機），
  雙擊 `run_daemon_install.command` 安裝/重載。日誌 `logs/reconcile_daemon.log`。
- **入口**：`python -m scraper.ordering.reconcile_daemon setup|once|cookies [probe]|run`。setup 在各口建控制分頁+勾選框；
  once 跑一輪（測試）；cookies 立即寫 cookie 狀態格（加 probe 連 1688 探測）；run 常駐（LaunchAgent 跑這個）。
- **★Cookie 過期警報（2026-07-22 #S096，`cookie_health.py`）**：解 Edwin「人在外面 cookie 過期就卡住、打勾當下才發現」
  的痛點。各控制分頁多一格 **B6「🔑 Cookie 狀態」**，daemon 每 6h 對每個 cookie 做**輕量探測**（帶 cookie 打一次
  1688 訂單 API `page=1,pageSize=1`）→ 🟢有效／🔴失效，並在打勾抓取遇 `SESSION_EXPIRED` 時**即時標紅**（附「該用哪個
  程式重登」提示，見 `relogin_hint`）。⚠️**探測才是權威、讀 cookie 檔到期日會誤報**：實測服飾 `cookies.json` 短命 cookie
  （cookie2 等）名目已過期 -8.7 天，但 1688 伺服器端 session **實打仍有效**（靠長命 cookie 撐）→ 故到期日只當「名目快到期」
  軟提示，**絕不單憑檔案報紅**。重登入口：美甲＝`run_reconcile_mac.command`「🔑登入美甲帳號」、服飾＝`run_mac.command`
  「🔑登入1688」、Baby＝登入 luwei03090826（待接專屬按鈕）。
- **待接**：到貨表（`【Nail】2-2.商品到貨記錄`）的口——抓**待收貨**訂單 + **運單號**（清單 API 遮罩地址/單號，
  可能要多打物流 API）→ 寫到貨表 50 欄 `1688_DB`。等 Edwin 金額表調好再啟用（JOBS 加一列即可）。還有其他 3 個賣場同模式。

## ★到貨核對 — Kkren(巧巧郎)集運已出貨抓取（2026-07-14 #S085）
到貨表(2-2)核對要「運送單號→件數/重量/包裹狀態/到貨日」，資料來自集運商 Kkren(巧巧郎)。
資料流：**Kkren 已出貨 → 中繼表 `181lP`(【中繼】巧巧郎出貨狀態) 的 `Kkren_Data` 分頁 →
IMPORTRANGE 進 2-2 的 `Kkren_DB` → 到貨日期分頁靠「物流單號」對 `1688_DB!AF 運單號」帶出**。
⚠️**到貨版 1688_DB 刷新＝合併累加、非整張覆蓋**（2026-07-27）：`ReconcileDB.overwrite(arrival=True)`
先讀舊 DB，新抓訂單為主、這次缺運單號時**回填舊值**、舊有但這次沒抓到的訂單（已離開待收貨）**整組保留**
（純函式 `pending_scraper.merge_arrival_grid`）。否則訂單一離開待收貨、運單號從 DB 消失 → 到貨分頁 XLOOKUP 全對不到。
**故到貨表刷新前不用再手動「凍結成值」**；金額版（2026-07-29 起）也改合併累加、共用 `merge_order_grid`
（保留已付款訂單、待付款訂單反映最新金額），金額日期分頁核對完仍要凍結成值。
- **抓取（去風險定案）**：Kkren 是 SPA（`kkren.com.tw`），API 在 `api.jyb.com.tw`，認證＝
  **localStorage 的 `accessToken`（Bearer）**，非 cookie。Edwin 用 `kkren_probe`（scratch）登入一次
  存**完整登入態** `config/kkren_state.json`（含 token，⚠️新裝置登入要簡訊驗證碼）；之後 httpx 帶
  Bearer 直接打 REST，無頭自動、免再登（token 過期才重登）。
- **已出貨端點**：`GET api.jyb.com.tw/jyo/v1frontend/jyorder/index?...&jyoPayStatus=9&jyoStatus=5`
  （9=已付款、5=已出貨）。**一訂單多包裹→一列一 `parcels[].trackingNo`（物流單號）**。
- **欄位對應**（`kkren_scraper.to_parcels`）：oid→訂單編號、createdAt→下單日期、
  `jyoExtraInfo.schedule.calJycutAt`週幾→結單日(星期X結單)、`.calDelivAt`週幾→預計到貨、
  **`parcels[].trackingNo`→物流單號**、`parcels[].weight÷1000`→重量(KG，實測1980→1.98)。
  ⚠️**物流狀態抓 `order.subtnos[].lastTrace`（自派車軌跡，自帶時間戳、出貨後才有）**，靠
  `jyoExtraInfo.parcelsInfo.estimateSubtnos` 對回各 parcel 物流單號（`_subtno_trace_map`）；沒有才退回
  `parcels[].statusAt+statusBrief`（＝Kkren 倉庫打包狀態，會凍在「已打包」，**不是**真實貨態，別只抓這欄）。
  ⚠️到貨日**自帶在每筆訂單** schedule，不用另查行事曆。
- **去重 append**：比對 `Kkren_Data` 既有「物流單號」(第5欄)，只加新的（Edwin「只抓還沒建立過的」）。
- **入口**：CLI `python main.py kkren-refresh [-d 天數] [--commit]`；daemon **到貨口**（`also_kkren:True`）
  打勾時**同時**刷 1688 待收貨 + Kkren 已出貨（一個勾更新 1688_DB + Kkren_Data）。
  ⚠️**到貨口＝兩段獨立**（2026-07-27，`_run_job` arrival 分支）：1688→1688_DB 與 Kkren→Kkren_Data
  各自 try、互不阻擋，1688 逾時/0 筆時 Kkren 照樣更新（狀態格分開回報 `1688：…；Kkren：…`）。
  因 1688 訂單清單 API（`OrderListDataLineService.buyerOrderList`）常態 `TIMEOUT::接口超时`——連待付款也會，
  屬 1688 端/風控暫時性；`pending_scraper` 已調耐撞（timeout 60s、pageSize 50、退避重試），全逾時時仍需等 1688 恢復、勿狂按刷新。
- **✅ 端到端驗證**：1688 待收貨運單號（如 79016806016916）＝Kkren 物流單號，兩邊對得上；
  重量/到貨日與 Edwin 現有 Kkren_Data 逐筆一致。

## ★蝦皮數據中心每日抓取（scraper/shopee_analytics/，2026-07-22 #S098 起、#S100 廣告全層+排程收尾）
每天全自動抓 6 張表給 Claude 分析（承 #S097：**真相 = Google Sheet（Edwin 可核對）、SQLite 加速副本、raw JSON 原封快照**）。
API 規格（端點/參數/欄位/report_type 枚舉/限流）全在 **`docs/shopee_analytics_api.md`**，動這模組前先讀它。
- **認證**：登入 cookie（`SPC_CDS` 同時帶 query）。`shopee-login --shop {nail|lady|baby}` 開瀏覽器登入存
  `config/shopee_cookies_{shop}.json`（gitignored；實打 API 驗證才算成功）。多賣場同套程式換 cookie。
- **抓取**：`shopee-collect --shop nail [--date] [--sheet-id] [--no-sheet]`（預設抓昨天；sheet-id 預設查
  `settings.SHOPEE_ANALYTICS_SHEET_IDS`）。落地順序 raw 快照 → SQLite → Sheet。SA 沿用 inventory-sync
  （env `GOOGLE_SERVICE_ACCOUNT_JSON`，未設則 fallback `ORDER_SHEET_SA_JSON`；SA 要被分享 Sheet 編輯權）。
- **⚠️ 三賣場連寫爆 Sheets 讀取配額(429)＝2026-07-29 修**（#S104）：`shopee-collect-daily` 三家背靠背寫 Sheet，
  一分鐘內對 Sheets 的讀取次數超 60/分 → 429，且**寫到一半中斷會留下部分分頁缺當天資料**（lady 7/27 廣告+自動選品
  被截）。修法雙保險：① `shopee_collect_daily_cmd` **賣場間隔 30s 分段寫**；② `storage_sheet.save` 內建 **429 退避
  重試整包**（30/60/90s；`_save_once` 冪等故重試安全）。補歷史漏寫免重抓＝從 SQLite 重建 `DayData` 再 `storage_sheet.save`。
- **6 個 Sheet 分頁**（同日重跑冪等＝先 batch 刪舊列，⚠️逐列 delete 423 次會炸 429，見 `storage_sheet._delete_day_rows`）：
  1. `商品日報_YYYYMM`：商品層 `v4/product/performance/`（49 欄，分頁抓全店 ~423/天）
  2. `規格日報_YYYYMM`：規格層（inline models，994/天）——**「規格名稱」＝成本/毛利月獲利表對帳 key**
  3. `大盤日報_YYYY`：`sales/overview/funnel/` + `traffic-sources/` + `key-metrics/`（一天一列，尾段有廣告總計欄）
  4. `廣告日報_YYYYMM`：廣告活動層。`POST pas/v1/homepage/query/`（**兩種 campaign_type 合併**：
     `cpc_homepage_v3` 手動+自動加碼+賣場 + `product_gms` 自動選品聚合）。⚠️金額欄 ÷100000；只留當天有跑的活動
  5. `自動選品商品_YYYYMM`：GMV MAX 逐商品（74/天）。自動選品 UI 是黑箱一列，逐商品靠 **export_job flow**
     （`gms_detail.py`：trigger `product_gms__homepage` → 輪詢 → download 回 CSV 全文）。挑高 ROAS 商品轉手動
  6. `賣場廣告關鍵字_YYYYMM`：手動賣場廣告逐關鍵字（投放詞×買家搜尋詞，只留有花費/轉換 ~330/天）。
     `shop_keyword.py` 走同 export_job flow（`shop_manual__single_detail`，帶 campaign_id；從當天廣告日報篩 shop_manual 活動）
- **⚠️ export_job 限流**（`trigger` 回 `code=200 too many export requests`）：多活動連續匯出必撞 →
  `gms_detail.run_export_job` 退避重試 15/30/45/60s + 賣場關鍵字活動間 sleep 8s。全域 export helper＝`run_export_job`。
- **中文表頭**：三分頁欄名全中文（`storage_sheet._CN`/`_cn()`；英文 key 只在 code/SQLite/raw）；`_ensure_ws` 表頭不符自動遷移。
- **每日排程（#S100 已裝）**：LaunchAgent `com.joyslu.shopee-analytics.plist` 每天 10:30 跑 `shopee-collect-daily`
  （loop `SHOPEE_ANALYTICS_SHEET_IDS` 所有已登入賣場，缺 cookie 略過、一店掛不影響其他）。
  裝：雙擊 `run_shopee_analytics_install.command`（同時裝健康點名）。
- **★數據健康點名（#S100，`health_check.py`）**：解「排程沒跑＝連失敗通知都沒有」的無聲失敗。LaunchAgent
  `com.joyslu.data-health.plist` 每天 11:00 **驗資料本身**（點名制，非聽作業回報）：蝦皮**同時驗 SQLite + Google Sheet**、
  ERP 查【全】ERP庫存寬表 H1 欄頭＝今天（`ERP_SHEET_ID`）。結果跳 **macOS 對話框**（`alert_mac` 停螢幕不消失，
  比橫幅可靠）+ 寫「抓取狀態」分頁（歷史）。異常才補橫幅+提示音。1688 核對 daemon 不點名（主動勾選型）。
  ⚠️**蝦皮加驗 Sheet＝2026-07-29 修盲點**（#S104）：原本只查 SQLite → 429 漏寫（SQLite 有、Sheet 缺）時**誤報全綠**。
  現 `_sheet_missing_tabs` 比對「SQLite 有料的分頁」是否也寫進 Sheet（該日該賣場列數 < SQLite 就判 ❌ `Sheet漏寫`）；
  Sheet 讀不到只註記 `Sheet未驗` 不判死。
- **★訂單商品聯動 basket（#S101，`order_basket.py`）＝每月一次半自動**（Edwin 定義，不每天抓——
  basket 是慢變數 + 訂單報表含個資）：Edwin 每月匯出訂單報表（`Order.all.*.xlsx`，msoffcrypto 加密、
  **密碼＝帳號手機末 6 碼**，美甲＝576137）丟過來 → `order-basket <報表> -P <密碼> --commit`。
  解密只取訂單/商品/貨號/數量（**不碰個資欄**）、排除不成立單 → 落地 Sheet `訂單明細_累積`（去個資、
  月 append 去重）+ `商品聯動摘要`（從累積所有月重算：買A配B共現 + 常買多件）。用商品ID 聚合到商品層。
  ⚠️簡訊驗證只在「觸發下載」那步（Edwin 手機手動），讀已下載檔免簽章。
- **★三賣場全開（#S102 結案）**：nail/lady/baby 各一份 cookie + 各一張 Sheet（ID 在
  `SHOPEE_ANALYTICS_SHEET_IDS`，**未填 ID 的賣場自動排除排程**）。實跑三家 0 失敗、資料零串台，
  健康點名自動變四行（三家+ERP）。⚠️**蝦皮無切換賣場 API**（session 綁登入當下賣場）→ 一賣場一份
  cookie 是唯一解；企業帳號可用（一組帳密切三次賣場登入）。**簡訊驗證/選賣場只在登入那一次**，
  之後排程無頭直打 API 免驗證；cookie 長效，過期才重登（健康點名會抓到）。
- **待接**：model_id ↔ 商品選項貨號 對照（models 沒帶貨號，跟訂貨/庫存 join 需要）。

## ★三賣場數據 AI 分析層（scraper/shopee_analytics/，2026-07-26 #S104）
把每天抓好的三賣場數據「重新接回去」變成 Edwin 一眼可用的東西。定調（Edwin 拍板）：
**本質不是做完善 dashboard，是「AI 每天替我讀完三家數據 → 直接給結論和待辦」**＝出錢請的專業店長顧問。
紀律＝**少而精**、只抓觸發決策的幾個關鍵數，不做每商品多分析點。**先 Google Sheet 版**跑第一版，
之後才做畫面（要接 personal-os-dashboard 監控層再說）。三塊，都寫進「戰報 Sheet」（3 分頁）：
- **1. 每日戰報（`daily_report.py`）**：一眼看三賣場。矩陣＝**8 關鍵數**（列）× 三賣場（每家 值/昨比/週比）。
  8 數（改 `metrics.py` 的 `METRICS` list 即增刪）＝成交額/成交訂單數/成交轉換率/CTR/訪客下單率/廣告花費/廣告ROAS/廣告佔營收比。
  昨比＝vs 前一天、週比＝vs 7 天前，帶 🟢🔴▲▼（**不靠 Sheet 條件式格式**，手機也一眼）。每次跑覆蓋整頁＝只呈現最新一天。
- **2. AI 店長顧問（`advisor.py` + `signals.py`）**：每天一則白話＝今天一句話/✅維持/⚠️動作/🔎機會。
  價值在**跨表交叉**（商品×廣告×大盤）：`signals.py` 抽「銷量爆發/有看沒買/關鍵字燒錢零轉換/高ROAS關鍵字/
  自動選品高ROAS/廣告佔比過高/轉換·CTR·營收週比驟降」→ digest → Claude（`claude-sonnet-4-6`，同 copywriter）。
  **無 `ANTHROPIC_API_KEY` 或呼叫失敗 → rule-based fallback**（照樣條列訊號、不開天窗）。冪等：同資料日覆蓋、否則插最上面。
- **3. 改動追蹤日誌（`change_log.py`）**：閉環「改了什麼→有沒有變好」。一張分頁，左半 Edwin 填
  （改動日/賣場/對象/類型/改了什麼/想改善的指標）、右半系統每天自動算（改動前後 3/7 天目標指標+變化%+判定）。
  系統無法自己歸因（看得到 CTR 掉但不知是改了標題）故「改了什麼」要人填。**對象填商品ID＝追該商品、留空＝追整店**；
  領先指標(CTR/轉換)3-7 天可判、落後指標(營收)拉長，故同時給 3 天與 7 天兩窗。判定門檻在 `change_log.py` 頂端。
- **orchestrator `analysis.py`**：`run_analysis(day, db_path, sheet_id)` 依序寫三塊。**掛在 `shopee-collect-daily`
  尾巴**（三家抓完、有任一家成功就跑，讀 SQLite 重算）。也可獨立重跑：`shopee-analyze [--date] [--no-ai] [--sheet-id]`
  （不重抓，純讀 SQLite 重寫）。
- **寫哪張表**：`settings.SHOPEE_DASHBOARD_SHEET_ID`（env 可覆蓋）；**留空＝寫進 Nail 數據表**（SA 已有編輯權、
  第一版即可跑）。之後 Edwin 建一張獨立彙整表分享給同一 SA、填 ID 即改寫過去。
- **資料源＝本機 SQLite**（`shop_daily`/`product_daily`/`shop_keyword_daily`/`gms_product_daily`，有歷史）：
  成交額/訪客/廣告花費·ROAS 取 `shop_daily` 官方值（＝Edwin 大盤看到的同一數好核對）；
  成交訂單數/曝光/點擊 `shop_daily` 沒有 → 用 `product_daily` 全店加總導出（CTR＝Σ點擊/Σ曝光）。
- **⚠️這台 Windows 無本機蝦皮 SQLite**（daemon+DB 在 Mac）→ 純運算已用合成資料驗過，**真實端到端要在 Mac 跑**
  （有 AI key + 真資料）：`shopee-collect-daily` 自動帶、或手動 `shopee-analyze`。
- **待接（#S104 下一步）**：① Edwin 確認 8 個關鍵數要加/拿掉哪些（改 `METRICS`）；② 顧問⚠️動作自動變追蹤日誌一列
  （閉環再黏緊，現為手填）；③ 跑幾天後對螢幕核對數字；④ 之後接 dashboard 畫面。

## 環境變數
- `ECOMMERCE_DESIGN_DIR` — 生圖設計規範資料夾。#S130：`scraper/{gpt_image_generator,auto_classify,image_host,video_maker,size_chart_maker}.py` 已改為 re-export shim → 真碼在 `ecommerce-media` 套件。gpt_image_generator shim 會自動把此 env 指回 `config/design_engine`（品牌政策留本 repo），一般不用手動設。
- `ANTHROPIC_API_KEY` — Claude API key（文案引擎 copywriter.py + 分析層 AI 店長顧問 advisor.py）
- `SHOPEE_DASHBOARD_SHEET_ID` — 三賣場分析層戰報表 ID（留空＝寫進 Nail 數據表，#S104）
- `OPENAI_API_KEY` — GPT 生圖（gpt-image-1.5）
- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`（`sb_secret_…`）/ `SUPABASE_BUCKET`（預設 `joyslu-images`）
  — GPT 生圖圖床（Supabase Storage public bucket；只 GPT 路線用）。service key 是機密，勿 commit。
- `GEMINI_API_KEY` — Google Gemini API key（舊文案/生圖，保留備用）
- `RECONCILE_SHEET_ID` — 金流核對表（【Nail】進貨金額記錄）ID，reconcile-refresh 覆蓋其 `1688_DB` 分頁（預設已寫死；SA 同 inventory-sync）
- `KKREN_SHEET_ID` — Kkren 中繼表（【中繼】巧巧郎出貨狀態）ID，kkren-refresh append 其 `Kkren_Data` 分頁（預設已寫死）。Kkren 登入態存 `config/kkren_state.json`（機密，gitignored）
- `SHOPEE_ANALYTICS_SHEET_ID_NAIL` — 【Nail】蝦皮數據中心 Sheet ID（`settings.SHOPEE_ANALYTICS_SHEET_IDS`，預設已寫死；Lady/Baby 之後各加一張）。蝦皮 cookie 存 `config/shopee_cookies_{shop}.json`（機密，gitignored）

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
