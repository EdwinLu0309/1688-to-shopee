# 1688-to-shopee

## 專案簡介
1688 商品資訊爬取 → AI 生成蝦皮文案 → 蝦皮批次上架 Excel 自動產生。

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
├── main.py                    # CLI 入口（login/scrape/generate/batch）
├── config/
│   ├── settings.py            # 全域設定（含 Gemini、Google Sheet）
│   ├── shopee_template.xlsx   # 蝦皮批次上架模板
│   └── browser_profile/       # Playwright 登入 profile（gitignored）
├── scraper/
│   ├── models.py              # Product1688, SKUOption, PriceRange
│   ├── extract_1688.js        # 抓取法A：Chrome MCP 注入此 JS 抽 DOM → Blob 下載 JSON
│   ├── playwright_scraper.py  # ★抓取法B（GUI 用）：Playwright+cookie+stealth 抽 DOM（免 Chrome MCP，同一套選擇器）
│   ├── data_extractor.py      # （已失效）__INIT_DATA__ 提取，現代 1688 已無此全域變數
│   ├── item_page.py           # Playwright 爬取 + DOM fallback（反爬擋下，未使用）
│   ├── network.py             # XHR 攔截 + SKU 解析
│   ├── browser.py             # Playwright persistent context
│   ├── login.py               # 手動登入模組
│   ├── downloader.py          # 圖片下載（主圖/細節/SKU）
│   ├── ai_generator.py        # Claude API 生成蝦皮標題/描述（保留備用）
│   ├── gemini_generator.py    # Gemini API 多模態生成文案+電商圖片
│   ├── sheet_reader.py        # Google Sheet 採購表讀取（hyperlink 提取）
│   ├── shopee_excel.py        # 蝦皮 Excel 模板填入（zip 直改保留隱藏 sheet）
│   ├── copywriter.py          # ★文案引擎：Claude + SOP 生標題/詳情/簡稱/變體命名（build_variants）
│   ├── video_maker.py         # 蝦皮短影片合成（本機圖→1:1 mp4，ffmpeg）
│   ├── pipeline.py            # 單商品全流程串接
│   └── batch_pipeline.py      # 批次處理（採購表→逐一處理→合併 Excel）
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

## AI 名單怎麼從 Google Sheet 落地成 CSV（私有表，路 B 已自動化）
名單是**私有** Google Sheet（`AI_LIST_SHEET_ID`，見 settings.py），公開匯出 URL 會 401。
**路 B（現行，一鍵）＝收割日常 Chrome 的 Google session cookie**（`scraper/chrome_cookies.py`
+ `sheet_fetcher.py`；GUI「⬇️ 更新名單」/ CLI `python main.py fetch-list`）：
`chrome_cookies.get_cookies("google.com", profile)` 解密（macOS：`security` 取 "Chrome Safe
Storage" → PBKDF2-SHA1(saltysalt,1003) → AES-CBC v10）→ httpx 帶 cookie 打
`/gviz/tq?tqx=out:csv&gid=<gid>` → 存 `input/lady_ai_list.csv`。逐一 Chrome 設定檔試，
第一個抓到合法 CSV 的就用（自動判斷哪個 profile 登入了名單那個 Google 帳號）。
不開瀏覽器、不登入、不碰驗證。解密法移植自 listing-optimization-tool 的 `grab_session.py`（#S065）。
⚠️ cookie 解密**只實作 macOS**；Windows（DPAPI + AES-GCM）待補。
⚠️ 讀舊本機 CSV = 讀到舊資料：實際踩過本機檔停在 2 商品舊版、線上表其實已 48 商品。
（備用：路 A＝登入 Chrome 開試算表分頁後同源 fetch gviz → Blob 下載到 ~/Downloads，Chrome MCP
`javascript_tool` 直接回傳 CSV 會被「Cookie/query string data」安全過濾擋掉，只能走 Blob。）

## 桌面 GUI（gui.py，一條龍、免打指令）
給非工程使用者的「按幾顆按鈕就上架」全包 App（tkinter，Win/Mac 雙平台）。
啟動：Mac 雙擊 `run_mac.command`、Windows 雙擊 `run_windows.bat`（皆優先用 `.venv`）。
流程：⬇️ 更新名單 → 勾選商品 → 🚀 一鍵完成（抓取→產出）→ 📁 素材。字體整體放大（可讀性）。
主按鈕是 **🚀 一鍵完成**（`_run_all_worker`：scrape_many 抓 → run_batch_two_tier 產，一次到底）；
下面「分步執行」保留 🔍 只抓取 / 📦 只產出 給需要重跑單一步驟時用。各步驟：
0. **⬇️ 更新名單** → `sheet_fetcher.fetch_ai_list`（路 B：解密日常 Chrome 的 Google cookie 抓
   私有 Sheet，免登入）→ 覆蓋 `input/lady_ai_list.csv` → 解析成**逐商品勾選清單**（顯示
   編號/推斷分類/名稱）。⚠️ cookie 解密目前只實作 macOS。
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

## 環境變數
- `ANTHROPIC_API_KEY` — Claude API key（文案引擎 copywriter.py 用，標題+詳情）
- `OPENAI_API_KEY` — GPT（之後電商生圖用）
- `GEMINI_API_KEY` — Google Gemini API key（舊文案/生圖，保留備用）

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
9. **主商品貨號（`ps_sku_parent_short`）留空**（變體商品填了會「型號與變體不匹配」）。
10. **危險物品（`ps_dangerous_goods`）留空**（= 預設否；不要填 Yes/No/是/否）。
11. **商品選項貨號＝型號（`ps_sku_short`）純英數、不可含中文**，每個顏色一個（如 `P-a1-1`）。
    含中文 → 「型號與變體不匹配」。
12. **物流**：啟用的頻道填 `開啟`，停用的**留空**（不必填「關閉」）；每列都填。
13. **分類（`ps_category`）填分類 ID（數字，如 `100358` 女生衣著/長褲）**，不是文字。
    ID 在模板「較長備貨天數範圍」sheet 查（`et_title_category_name`/`et_title_category_id`）。
14. **圖片**用 https 網址（1688 原圖即可，選填）；**品牌**基本模板沒欄位，UI 選 JoysLu（編號 6379087 通用）。

**二階規格命名（與庫存系統一致）：** 規格選項1 = `編號_商品簡稱_顏色`（底線可被庫存系統解析）；
規格選項2 = 尺碼（廠商有給體重/身高才加，如 `M(建議47-55kg)`）。`copywriter.build_variants` 產生。

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
