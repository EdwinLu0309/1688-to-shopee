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

## ★新品建檔 → 1-1 待貼分頁（master_staging.py）— 上架與訂貨的銜接

兩條路共用「抓 1688 → AI 文案 → 蝦皮 Excel」：**預購**到此為止；**正式新品**多一步——把商品
寫進該賣場 1-1 商品主表的 **`_待貼新品`** 暫存分頁，人補編號後貼進 商品表/SKU表，訂貨表
QUERY 自動長出 → 接上 1688-order 自動加購與 2-1/2-2 追蹤。

- **哲學同 inventory-sync `_raw_import`**：1-1 是全系統地基，機器只寫暫存分頁不碰正表；
  商品編號本來就要人給，讓人介入發生在「貼上」而非「事後修改」。
- **入口**：GUI「🆕 正式新品」勾選（一鍵完成/產出都吃）；CLI `batch2 --staging [--staging-force]`。
- **版型**：上下兩區塊、各自鏡射目標分頁欄序、都從 A 欄對齊。上區塊→商品表（A~U）、
  下區塊→SKU表（A~P）；右側外掛「(勿貼)」輔助欄（1688ID/名單編號/規格顯示）。
- **機器填**：規格一/二（**1688 原文逐字，絕不可轉繁**——cart_adder 拿去頁面比對）、代表網址
  （正規化 offer/{id}.html）、品名（AI 繁體簡稱）、分類、幣別「人民幣」；成本/廠商抓得到才填
  （現行抓取器價格覆蓋率低、廠商名未實作，缺就留空給人）。**人填（黃底）**：商品編號/蝦皮售價/
  特殊訂貨%（商品表）；ERP品號/標籤/安全存量（SKU表）。**公式欄留白**：商品表 F/H/I/R~U、
  SKU表 K/O/P 都是正表整欄陣列公式，貼上後自動長出。
- **SKU 品名公式**：B 欄 `=IF($A$3="","",$A$3&"_"&$D$3&"_"&R7)` 直接引用上區塊該商品列——
  人補完編號自動組 `編號_品名_規格`；貼到 SKU表 要用「選擇性貼上→僅貼上值」。
- ⚠️ **規格二原文對映**：size_labels 的 key 是 Claude 正規化的 S/M/L，1688 原文長相不定
  （`S【88-98斤】`/`S 适合75-105斤`）→ 取開頭字母數字 token 對映回原文（`_size_original_map`）。
- ⚠️ **覆蓋防呆**：分頁還有上一批沒貼走 → 拒絕寫入（`StagingNotEmpty`）；GUI 開跑前預檢
  （`staging_has_leftover`）在主執行緒跳「要覆蓋嗎」對話框，背景執行緒不跳 UI。
  機器分頁採**刪掉重建**而非 clear()（gspread clear 只清值不清格式，#S163）。
- ⚠️ **三家 1-1 表頭 2026-08-20 逐欄比對一致**（商品表 21 欄/SKU表 16 欄；Baby 已遷新版）。
  表頭常數寫死在 `master_staging.py` 頂部——正表改欄序要同步改。
- 待補（V1.1）：抓取器補「賣家公司全名」（2-1 對帳 join key，比店鋪名準）與買區 per-規格價
  （可借 1688-order `master_audit` 技術），成本/廠商就能機器填。

## 新品記號 #NEW＝SKU表 J 選項註記（2026-09-17 Edwin 定）
訂貨時篩新品用。`_待貼新品` 下區塊 J 欄自動寫 **`#NEW MMDD`**（建檔日期，例 `#NEW 0917`；綠底可貼）；**商品表不標**。搜「#NEW」照樣抓得到。
- ⚠️⚠️ **絕不可放 D 標籤**：Nail 訂貨彙總 B4 用 `'訂貨表'!D="#N_機器"` 這類**逐字比對 25 種標籤**、訂貨表 M 用 `D<>"#PO_Sale"`
  排除預購 → 標籤多一個 ` #NEW` 就整批從訂貨彙總／廠商訂單／進貨金額記錄消失、預購品被算進補貨，且不報錯。
  名單標籤若夾帶 #NEW，建檔時會被拿掉。J 欄只有訂貨表 Q 用 VLOOKUP 原樣顯示，沒有比對。
- J 欄原本有 Edwin 手寫的註記（(散)／7/16 缺…）→ 補標一律**接在原內容後面**，不覆蓋。
- 2026-09-17 已替 9/9 那批補標 27 個品號（`#NEW 0909`）（排除 HNV1/HNV2/HNV5 三支舊主機 AH0030015010001/AH0030014010001/AH0030012010001——
  9/9 是把濾網濾紙加成它們的新選項）；寫後驗證訂貨彙總 B2:F3 與訂貨表列數不變、其他列 0 異動。

## ★SKU 品號生碼器（`scraper/sku_code.py`，2026-08-28 #S194）

規則正本＝`1688-order/docs/上架訂貨統一架構.md` §5-3。Lady 15 碼：
`B(賣場)｜H(分類字母)｜003(子分類字母序)｜0002(款號)｜0006(顏色序)｜03(尺寸序)`。

- ⚠️ **顏色／尺寸序＝我們實際要進貨販售的流水號，不對應 1688 頁面位置**
  （既有資料看似位置編碼且跳號，實為「後來不賣了刪掉」造成）。
- ⚠️ **鐵律：號碼只發不改、刪掉的號不回收（append-only）**，新號＝該商品現有最大號+1。
  回收號碼會讓蝦皮歷史訂單／ERP 舊紀錄／獲利表 join **靜默串到錯的商品**。
- ⚠️ **比對「這個選項是否已有碼」一律用 1688 原文**（SKU表 L/M），不可用品名裡我們取的
  繁體名——`紫色`（我們）vs `067-卡其`（1688 原文），拿繁體名去頁面找永遠找不到。
- ⚠️ **三家品號體系完全不同**（Lady 15碼B開頭／Nail 15碼A開頭但尾碼結構不同、品名前綴是
  品牌碼 `CHE`／Baby 14位純數字）→ **未支援的賣場直接拋 `UnsupportedShop`**，
  品號欄留空給人補，**絕不硬套 Lady 規則產出看似合法的錯碼**。
- 回歸測試 `tests/test_sku_code.py`（31 項，用線上實測樣本對答案）。

## ★Nail SKU 品號生碼器（`scraper/sku_code_nail.py`，2026-09-07 #S208）

**與 Lady 是兩套完全不同的體系，刻意不共用**（Edwin「三賣場不共用」指示；實測也證明不能共用）。

```
A   A     006     0003    01     0000
賣場 大分類 品牌3   商品序4  款式2  顏色4      ＝ 15 碼
```
- **商品編號自己也解得開**：`AAS1` ＝ 大分類 `A` ＋ 品牌 `AS` ＋ 序號 `1`（**無連字號**，
  與 Lady 的 `H-c2` 不同 → `_code_letters` 已改 per-shop，否則 Nail 的分類推導全部落空）。
- ⚠️ **「商品序」是 Edwin 的商品定義，不是 1688 連結**（2026-09-07 澄清）：同一款基礎膠
  （底膠／免洗封層／建構膠）有些廠商放同一連結、有些分散 → 機器推不出來。預設開新號；
  要掛既有系列由 AI 名單新增的**「歸屬」欄**指定（填既有商品編號如 `AAS1`）。
  **款式＝該商品序底下的第幾個連結／品項**，顏色＝該款式底下的規格組合序（無規格＝0000）。
- ⚠️ **發號一律「現有最大 +1」，不補中間空號**：品牌碼有跳號（001/004/006…）。補空號會讓
  新品號排在既有品號**前面** → SKU 表排序時第 2 列（K/O/P 陣列公式錨點）被推走、三欄整片
  變空白且不報錯。往最大值後面發就永遠不會發生。
- ⚠️ **未知品牌一律拋 `UnknownBrand`，不自己編號**（撞號不會有錯誤訊息，只會讓兩個品牌
  混在同一號段）。訊息會提示「照最大+1會是幾號」讓 Edwin 決定。
- ⚠️ **顏色序補零到 4 碼**：既有 55 列曾寫成 5 碼（`00010`／美潮48色 48 列＋VDN 6＋Krisno 1），
  2026-09-07 由 Edwin 全數刪除（都是售完商品）。
- 實測（線上 4,419 列）：推出 40 個品牌、44 個商品序組、356 個可歸屬編號；
  新品 `AAS99` → 商品序 0008；歸屬 `AAS1` → 款式 21（正確接續 AAS3 的 20）。
- 回歸測試 `tests/test_sku_code_nail.py`（30 項，樣本取自線上真實資料）。

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
│   ├── product_card.py        # 商品資產包（廠商固定事實商品卡 + 圖/影片/raw）
│   └── master_staging.py      # ★正式新品 → 1-1「_待貼新品」暫存分頁（接訂貨流程，2026-08-20）
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

## 產出目錄（2026-09-14 定版）
```
input/{shop}_ai_list.csv          名單抄本（自動產生，手改會被蓋掉）— **一賣場一個檔，就這三個**
output/
  raw/{item_id}.json              1688 原料，**刻意扁平不分賣場批次**
  raw/{item_id}/ai_content.json   文案快取
  batch/{shop}/{YYYYMMDD}/        ★ 一次跑一夾，舊批次永不被覆蓋
      名單快照.csv ／ 批次說明.md
      文案_v1/  上架檔.xlsx ／ 素材/{編號}/ ／ manifest.json
      文案_v2/  ← 換模板或改規範重產，v1 完整留著
```
- ⚠️⚠️ **產出一律開新版本號，永不覆蓋**（Edwin 2026-09-14）：「你不能確定版本二比版本一好，
  如果三個版本都不如預期，有可能直接採用版本一重新上傳」。蝦皮的批次上傳是丟進**待上架區**
  給人審，不是直接上架 → 品質不 OK 就重產重傳是正常動線，所以每一版都要留得住。
  `批次說明.md` 每產一次追加一列（版本／時間／模板／商品數），**最後一欄「你的評語」留白**
  給 Edwin 自己標 OK/NG，挑版時只看這張表。
- ⚠️ **重傳會在待上架區多一筆重複**（蝦皮不依商品貨號覆蓋，Edwin 2026-09-14 實測）→
  產第 2 版以上時 log 會提醒「先去待上架區刪掉上一版」。
- **文案模板＝一份 SOP md**：`config/sop/{shop}/*.md` 每多一份就多一個下拉選項，不用改程式；
  換模板會分開存文案快取（`ai_content_{模板}.json`），不會讀到舊模板的快取。
  ⚠️ Lady 的 SOP 在 `config/sop/` 根目錄（沒有 lady/ 子夾），`copy_templates()` 兩邊都掃。
- **四個資料夾各有身分，別混**（2026-09-14 定）：`input/` 只放三家的名單抄本｜
  `output/` 只放 `raw/`＋`batch/`｜`tests/` 是**回歸測試程式**不是測試資料｜
  其他臨時產物一律 `scratch/`（gitignore，隨時可整個刪）。
  這條是清理 3.5G→433M 之後定的：當時 `input/` 躺著 7 月的舊名單副本、根目錄十幾個
  `scratchpad_*.log`、`output/` 混著測試 xlsx——每個當下都想「先放這等下整理」。
- **已上架之後才要改文案不走這條**（那是蝦皮後台／直接找 Claude 改）；這裡處理的是
  「待上架區看了不滿意」那一段。
- **raw 為什麼扁平**：key 是 1688 的 `item_id`（全站唯一），同一個連結會被不同批、不同賣場
  用到；分層放會下載兩份又分不出哪份最新。程式也是拿 item_id 直查。
- **manifest.json ＝ 編號 ↔ item_id ↔ 品號 的唯一完整對照**。事後問「HNV7 哪天上的、
  配到哪些品號」翻它就有，不必從 1-1 反推。GUI 清單的「✅ 已產出 MM/DD」也是讀它。
  （9/9 那批的 manifest 是 9/14 事後補寫的，當時程式還沒有這個檔。）
- ⚠️ **素材跟著批次不跟著編號**：舊版放 `output/上架素材/{編號}` → 同一支改版重跑直接蓋掉
  上一版，事後分不出哪個對應哪次上架。

## 搜尋詞庫（`scraper/keyword_pool.py`，2026-09-16 建，Nail 先行）

Edwin 逐字在蝦皮廣告後台查回 321 個詞的實際搜尋量 → 「【Nail】搜尋詞庫」Google Sheet
（`1lCZ-NP63Eyv…`，單一分頁＋`分類` 欄篩選）。文案引擎生標題時把「這一類能用的詞」
餵進 prompt，尾串不再寫死在 SOP 裡。欄位：`詞｜搜尋量｜查詢日｜分類｜位階｜相關性｜狀態｜備註`。
**Edwin 只填搜尋量**，其餘由 Claude 維護。

- ⚠️⚠️ **量大不等於能用**（Edwin 2026-09-16 指出，本場最值錢的一條）：`過濾棉 11622` 是魚缸／
  空氣清淨機濾材、`分裝瓶 48203` 是化妝品、`打磨機 8184` 是木工五金、`桌上收納盒 25885` 是文具。
  **搜這些字的人不會買美甲用品**，把他們引進來只會拉低點擊率與轉換，廣告還要付錢 →
  `相關性` 欄標「泛用」，程式只取「美甲」。22 個泛用詞剛好就是表面上量最大的那幾個。
- ⚠️⚠️ **「廣域」只能放真正跨品類的詞**：`貓眼 48857`／`卸甲 11101` 原本被歸廣域 →
  每一類都抓得到，集塵器的標題會出現「貓眼」＝買錯流量。已歸位到各自品類；
  **分類支援多值**（`光療＝膠,美甲燈`），一個詞只維護一列。
- ⚠️ **品牌詞可投廣告、不可進標題**：`莎夏美甲美學用品 7366`、`愛美佳美甲 2269` 這類競品字
  拿去下廣告關鍵字是常規操作，寫進自家標題是侵權與不實標示 → `位階=品牌` 一律排除。
- ⚠️ **死詞留著不刪**（`光撩燈 0`／`烘甲燈 5`）：刪掉三個月後會有人再查一次。靠 `狀態` 過濾。
- **實測推翻語感**：`磨甲機 28139` 比 `美甲打磨機 4054` 大 **7 倍** → 黏著首詞用哪個品類詞
  要看實測量，不能憑順口。`美甲除塵器 0`、`美甲店專用 0`、`空心杯打磨機 47` 這類組合詞幾乎沒量。
- **品類判斷用品名不用蝦皮分類 ID**（美甲工具底下同時有集塵器／打磨機／收納盒，分不出來）；
  品名認不出時退回 1688 原標題，所以關鍵詞**繁簡都要列**（`SUN3 48W 智能二代` 只有簡體「美甲灯」認得出）。
- ⚠️ **分頁名與欄名會被改**（「詞池」→「搜尋詞庫」）→ `TAB_CANDIDATES` 給候選、缺欄位大聲 warning。
  靜默回空會讓標題默默退回沒有關鍵字的版本。
- **兩道程式防線取代叮嚀**：①產出一律過 opencc `s2tw`（實測 HNV7 標題吃了 1688 規格名的「美规」，
  規範明文禁簡體也照樣漏）②`unverified_specs()` 檢查標題裡的數字＋單位在來源找不找得到——
  一個 1688 網址常掛好幾款（同頁有「302吸塵打磨機二合一／G1S渦輪美甲吸塵器／吸塵器濾網」），
  **頁面標題描述的是最強那款**，把它的瓦數寫到我們賣的那款上就是不實標示。

## 上架庫存（2026-09-16 Edwin 定）
- **預購固定 200**（名單不填；與 1-1 `_待貼新品` 的安全存量 200 同一個數）。
- **現貨＝AI 名單 F「安全存量」**（＝首批訂貨量＝進貨量＝上架庫存）。
- ⚠️ **現貨沒填安全存量 → 擋下並列出編號**，請去名單填好、更新名單後重建。**不可退回寫死的 10 件**
  （9/8 以前就是這樣，上架庫存跟實際進貨量對不起來而且沒有任何訊號）。GUI 在「🚀 開始」「✏️ 重生文案」
  按下去就擋；`run_batch_two_tier(make_staging=True)` 另有一道防線（CLI 也擋）；試跑不擋（那份不能上架）。
- 重量／長寬高沒有也能上架 → **不處理、核對表也不列**。
- 回歸測試 `tests/test_stock_channels.py`（15 項）。

## Nail 標題＝規範 v2.2（`scraper/title_check.py`＋`keyword_pool.py`，2026-09-17 接進自動上架）
正本 `~/Downloads/NAIL_標題優化規範_v2.2_2026-09-16.md`；SOP §2 已照抄成 AI 讀得懂的版本。
- **公式**：化粧品（膠／卸甲膠液膏／溶劑／保養）`[最大詞][第二大詞][真實形態詞] ✅PIF合規 [品牌][色數/容量][詞庫詞到58~60]`；
  器材材料 `[最大詞][第二大詞][真實形態詞][型號/已驗證規格][詞庫詞]`。不放【JoysLu Nail】、不放編號、除 ✅ 零符號、化粧品禁「療」。
- **關鍵字判斷**（`prompt_block`）：給 AI【可用關鍵字】【第一行大詞候選】【建議尾串】＋需不需要 ✅PIF合規。
  大詞候選＝本類的詞、**和品名有共同字眼的排前面**（「膠」池同時有貓眼指甲油／底膠／建構膠，只照量排會讓底膠商品開頭寫貓眼指甲油）；
  化粧品的清單裡直接不給含「療」的詞。
- ⚠️ **分類規則的順序就是優先權**：貓眼**膠**要落「膠」池（貓眼膠 13,644／貓眼指甲油 16,963 在那），「貓眼」池是磁鐵／貓眼筆配件；
  凝膠清潔液、解膠劑是溶劑（排在膠前面）。新增了 卸甲／保養 兩條規則。
- **程式檢查**：自動修＝編號、✅ 以外符號、免運/出貨/現貨/隔日、詞庫標成泛用/他牌/死詞的詞、重複詞、超過 60 字從尾串砍；
  要人看（寫在**核對表標題格下一行 ⚠️**）＝少於 55 字、化粧品沒 ✅PIF合規／✅ 前寬度不在 9.5~20／出現療、規格數字找不到出處。
- 快取文案帶 `title_version`，規則改了自動重生；Lady/Baby 不受影響。
- ⚠️ **「光撩非光療」LA/LB 是 A/B 測試版，不進自動上架**（9/23 判完再決定）。
- ⚠️ **✅PIF合規 是「宣稱」**：程式對所有化粧品類一律放。新進的膠若 PIF 還沒做完，上架前要人拿掉。
- 搜尋詞庫 2026-09-17 修兩列誤植：`穿戴甲 155,622` 分類「美甲燈」→「甲片」（會讓燈的標題塞進穿戴甲）、`甲片 29,792`「工具」→「甲片」。
- 2026-09-17 實測：BVD4 `貓眼指甲油 貓眼膠 冰透晶石貓眼 ✅PIF合規 VENDEENI 24色 裸色甲油膠 美甲膠 甲油膠 色膠 美甲材料`（58 字、✅ 前寬 15.5）。
- 回歸測試 `tests/test_title_check.py`。

## Nail 詳情＝中間版本（`scraper/detail_builder.py`，2026-09-17 Edwin 定版）
程式搭框架、只填有把握的，其餘由員工在待上架區補（核對表「詳情 OK」那一格）。
| 段落 | 誰寫 |
|---|---|
| ✦ 商品特色 | AI（只依商品名與屬性表） |
| ✦ 商品規格 | AI（只列屬性表明確寫到、屬於這次上架款的；**沒有就整段省略，不寫「待補」**） |
| ✦ 使用方法 | AI（依品類通用步驟） |
| ✦ 款式說明 | **程式**列出這次上架的選項名稱（不解釋差異） |
| ✦ 注意事項 | **固定文案**依品類（光療／電器／工具耗材，`NOTICE`） |
- **拿掉**：賣場介紹（9/9 寫過「提供現貨」）、退換貨（蝦皮後台統一）、推薦搭配（AI 編出賣場沒有的商品）。
- ⚠️ **不讓 AI 讀詳情圖**（Edwin）：1688 一頁常掛十幾款、我們只進兩款，圖常是別款，特例寫不完 → 交給人看。
- 設定在 `shops.py` 的 `detail_rule`／`detail_version`（Lady/Baby 空＝沿用舊 8 區塊）；**快取文案帶版號，規則改了換版號就自動重生**。
  AI 多寫的段落由 `_strip_ai_extra` 從標題切掉。注意事項分類先看我們的品名、認不出才看 1688 標題（濾紙那列的頁面標題是「吸塵器」）。
- ⚠️ **實測 Nail 機器/耗材頁的 1688 屬性表抓出來是空的** → 「商品規格」幾乎都會被省略，靠員工補。
- ⚠️ **一頁多款的真實案例 HND17**：名單品名「M50」、款式備註「白色 黑色各2」，但同頁 M50 沒有白色、EN101MAX 才有白/黑 →
  AI 挑了 EN101MAX。**款式備註要寫型號**（例「M50 黑色、銀白色」），不然 AI 只能照顏色猜。
- 回歸測試 `tests/test_detail_builder.py`（16 項）。

## 上架核對表（`scraper/listing_check.py`，2026-09-17 Edwin 定版）
員工逐支核對用。**與 AI 上架名單分開、另一個檔**（名單純粹給 AI 上架用，混在一起會亂）：
【Nail】上架核對表 `1FnCcR7Ie0Qx…`（Edwin 的 Drive、與名單同資料夾，已分享 inventory-sync SA 編輯；
Lady/Baby 還沒建 → `.env` 設 `CHECK_SHEET_ID_{SHOP}`，沒設就在 log 報錯、不擋批次）。
- **自動寫入時機**：`run_batch_two_tier` 產完上架檔、有建檔時；**試跑不寫**。寫失敗只 `logger.error`（上架檔已產好）。
- **一次產出一個分頁，分頁名＝產出日期 MMDD**；**一列＝一個蝦皮商品（一個編號）**，HNV11 三個 1688 網址合成一支就一列。
- 左灰 A~K 程式寫：產出日｜版本｜編號｜蝦皮標題｜現貨/預購｜選項數｜售價｜選項名稱｜SKU 品號｜規格圖（✅ 全有／缺 N/M 紅底）｜1688 網址（「開 1688 ①②」每行一個連結）。
  售價／選項／品號在格子內**換行同順序**，員工一行一行對。
- 右黃 L~T 員工：待上架區有看到｜標題 OK｜詳情 OK｜選項/價格 OK｜規格圖 OK｜已正式上架（勾了整列變綠）｜美編換圖完成｜核對日｜問題備註。
- ⚠️⚠️ **資料來源是產出的上架檔**（`read_upload_rows` 直接讀 xlsx XML，openpyxl 讀不了蝦皮模板），**不是 AI 上架名單**——
  員工要對的是真正傳上去的東西（標題程式生、選項挑過）。只有現貨/預購、1688 網址取自這批處理紀錄。
- ⚠️⚠️ **不用 IMPORTRANGE 帶名單**：帶過來的左半邊會跟著名單變、員工的勾是原地死值 → 名單插列/排序就整片對錯支
  （同訂貨表 J/O/S/T 錯位）。現行＝程式寫死值；**同一天重產第 2 版照「編號」找原列只更新 A~K，員工的勾保留**
  （2026-09-17 真表實測：先寫 5 支、員工勾 HNV2，再寫 22 支＝更新 5、新增 17，HNV2 的勾/核對日/備註都在）。
  隔天重產＝新日期分頁。
- 版面：字體 14、框線、只有商品列有底色（空白列不上色）、凍結 2 列、篩選。**員工不要插列/排序，新欄加最右邊。**
- ⚠️ Google 試算表點連結一定先跳預覽框，改不掉；**Cmd＋點**直接開。
- ⚠️ 新分頁至少要 3 列：只有 2 列又凍結 2 列會被 API 擋（「can't freeze all visible rows」）；建分頁失敗會刪掉半套分頁。
- 回歸測試 `tests/test_listing_check.py`（13 項，不連網）。

## 規格圖片（2026-09-17 修，Edwin 定由程式抓）
- **抓的是 1688 每個選項自己的圖，直接填進上架檔「規格圖片」欄**；1688 沒放圖的選項（如「其他定制，旺旺咨询」）留空給人補。
- ⚠️ **舊抓取器只認色票按鈕 `.sku-filter-button`**（女裝版面），美甲的機器/耗材是「一列一個規格」
  （圖＋名稱＋¥價＋库存）→ **9/9 那批 26 支規格圖片欄一格都沒有**，而且不報錯。
- 現行＝以頁面狀態 `skuModel.skuProps[].value[] {name, imageUrl}`（原圖，兩種版面都有）為準，
  買區列 `.expand-view-item` 的 `<img>`＋`.item-label` 補位；key 存「原名」＋「去空白」兩份
  （買區列名稱是去空白切出來的：`5包-M3 吸尘器` vs `5包-M3吸尘器`，不存兩份就對不上）。
- 實測 4 頁：集塵器 5/5、美甲燈 4/5（缺的是旺旺咨询那列）、磨甲機 25 支全有、女裝色票 48/48 照舊。
- **抓取器版本 `SCRAPER_REV`（現為 2）寫進 raw json**：「🚀 開始」遇到舊版抓的 raw 當成缺、自動重抓（GUI「抓取」欄也不打勾）。
  2026-09-17 之前是「抓過就跳過」→ 9/9 那批按開始重產，規格圖照樣全空。**改了抽取內容就把 SCRAPER_REV +1**。
- 只改了 GUI 用的 `playwright_scraper.py`；`extract_1688.js`（Chrome MCP 手動備援）沒跟上。
- 回歸測試 `tests/test_sku_images.py`（7 項，真 Chromium 開靜態頁）。

## 文案快取＝一列名單一份（`ai_cache_path`，2026-09-17 修）
`raw/{item_id}/ai_content[_模板]__{編號}_{hash(編號|品名|款式備註|colors)}.json`。
- ⚠️⚠️ **舊版只用 1688 網址當 key**：同網址被名單多列用時第二列起沿用第一列的文案——
  HNV5 標題＝HNV2、**HNV11 三列（吸塵器／二合一／濾網）三個選項全變成 G1S 吸塵器**，不報錯（9/17 核對表抓到）。
- 「文案做過沒」＝快取存在**且** detail_version／title_version 是現行的（`cache_is_fresh`），GUI 狀態欄與開始流程同一個判準。
- 9/17 遷移：名單只用一次的網址把舊 `ai_content.json` 複製成新檔名（21 支沿用），共用網址的 5 列重產。
- 回歸測試 `tests/test_cache_keys.py`。

## 上架動線分兩段（2026-09-15 Edwin 定，GUI 照這個長）

**第一段＝把一支完整商品湊齊**（🚀 開始）：抓 1688 → 文案 → 配 SKU 品號＋寫 1-1 → 上架檔 → 影片。
語意是**「缺什麼補什麼」不是「全部重做」**，每一步先看做過沒，做過就跳過。

**第二段＝只重做不滿意的那一項**（分步按鈕）：`🔄 重抓 1688`／`✏️ 重生文案（產新版）`／
`🧪 試跑（不寫 1-1）`。產出都是新版本號，舊版留著，最後挑一版上傳。

- ⚠️⚠️ **「做過沒」一律從真實產物讀，不另存狀態檔**（Edwin 問過「是不是要有內部表格記」）：
  狀態檔會跟現實脫節——檔案刪了它還說做過，而那種 bug 最難查。
  抓取＝`raw/{item}.json`／文案＝`raw/{item}/ai_content_{模板}.json`／
  **品號＝1-1 SKU表（唯一正本）**／上架檔＝批次 manifest／影片＝`raw/{item}/video/{code}.mp4`。
  `manifest.json` 只記歷史，不判狀態——兩者混在一起就會互相汙染。
- **配號本身是冪等的**（2026-09-15 對真表實測）：同商品編號、同規格原文一律沿用舊碼，
  只有沒見過的規格才發新號（`HNV11` 三規格重跑＝沿用 3 新發 0；多一個規格＝沿用 1 新發 1）。
  所以「重跑會不會每次配新品號」的疑慮不成立；**但 1-1 那一步沒有 v2**——品號是 ERP／獲利表／
  蝦皮訂單共同的 key，配出去就固定。
- **按下去之前先把「這次會做什麼」列給人看**（哪幾支要抓、幾支重生文案、幾支配號、產第幾版），
  Edwin 2026-09-15：「我連溝通了幾回都還是不確定現在會出現什麼」→ 不要讓人從勾選去推。
- 因此**拿掉了兩個 checkbox**：「建檔」（正式與預購都要，不是選項 → 一律做，試跑改成獨立按鈕）、
  「抓過不重抓」（那是唯一合理行為 → 一律如此，強制重抓改成獨立按鈕）。
- 真正的選項只剩：**🎬 影片**、**✨GPT 逐支生圖**、**文案模板**、（待做）**圖片模板**。
- **圖片模板＝一份設計規範 md**：`config/design_engine/{shop}/*.md`，加一份就多一個下拉選項。
  ⚠️⚠️ 上游 `load_design_spec()` 是「**讀 DESIGN_DIR 底下所有 md 串起來**」，沒有賣場概念 →
  規範全平放在 `config/design_engine/` 時，Nail/Baby 勾 ✨GPT 會拿到**女裝**那套
  （人物比例／模特兒位置／穿搭情境），套在集塵器上會生出很怪的圖，而且**看起來像功能有在跑**。
  現行＝`gpt_image_generator.use_template(shop, template)` 在呼叫前把 `DESIGN_DIR` 指到
  `{shop}/`（改 env 沒用——那在 import 當下就定案），用完還原；該賣場沒有規範就**擋下不生**
  （GUI 直接錯誤訊息、pipeline 退回 1688 原圖），絕不拿別家的規範硬生。
- **生圖要先講錢**：`gpt-image-1` 1024×1024 high ≈ **US$0.17/張**，26 支就 US$4.4。
  文案一支幾分錢、圖不是同一個量級 → 確認視窗會列張數與估價。
- **圖片先走 1688 原圖**（Edwin 2026-09-15 選 A）：第一段用免費原圖把商品湊完整能上架，
  GPT 生圖留在第二段試，試出好模板再拉進第一段當選項。Nail 還沒有圖片設計規範。

## 桌面 GUI（gui.py，一條龍、免打指令）
給非工程使用者的「按幾顆按鈕就上架」全包 App（tkinter，Win/Mac 雙平台）。
啟動：Mac 雙擊 `run_mac.command`、Windows 雙擊 `run_windows.bat`（皆優先用 `.venv`）。
流程：⬇️ 更新名單 → 勾選商品 → 🚀 一鍵完成（抓取→產出）→ 📁 素材。字體整體放大（可讀性）。
⚠️ **「⬇️ 更新名單」是必要動作，沒按就按不動「🚀 一鍵完成」**（Edwin 2026-09-14 要求做成硬性擋住）：
程式跑的是 `input/{shop}_ai_list.csv`——線上名單的**本機抄本**，不更新就是拿舊抄本去跑，
而線上新增的商品**根本不會出現在勾選清單裡**（踩過：本機停在 2 支、線上其實 48 支；
看起來一切正常，只是那幾支不會被做）。`self.list_fresh` 為 False 時一鍵鈕顯示
「🔒 請先按『⬇️ 更新名單』」並轉灰，點下去跳說明。**切賣場、手動「選檔…」都會重新上鎖**
（換一家＝換一份名單；手挑的 CSV 可能是很舊的抄本）。
⚠️ 刻意**不用「超過 N 小時才提醒」**：那會留下「剛好沒過期但線上剛改過」的縫，而這個縫
正是這條規則要防的情境。分步執行的「🔍 只抓取／📦 只產出」不上鎖——那是壞掉時的補救路徑。
⚠️⚠️ **「🆕 建檔」預設開，取消勾＝試跑**（2026-09-14 Edwin 改；原本預設不勾是錯的設計）：
正式與預購都住 1-1、都要有 SKU 品號，所以「不建檔的產出」不是正常路徑。不建檔時 Excel 的
`O 商品選項貨號` 只能退回「HNV7_美規」這種字串，而獲利表是拿「蝦皮選項貨號＝SKU 品號」
去 join 成本與銷量 → **這批商品上架後在獲利表裡整片是黑的，且沒有任何錯誤訊息**。
現行兩道防線：取消勾選會跳確認框講清楚後果；產出的檔名改成 `上架檔_試跑.xlsx`。
CLI 同步：`batch2 --staging` 預設 True，要試跑得明寫 `--no-staging`。
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
    **現貨／預購分流（Edwin 2026-09-16 定，`shops.channels_for`）**：
    - **現貨**＝較長備貨天數**留空**（走賣場一般備貨天數＝1 天）＋公版 6 個＋**`30019` 蝦皮店到店－隔日到貨**（跟開 7-11／全家一樣填「開啟」）。
    - **預購**＝較長備貨天數 **10**（Nail 分類可填範圍 2~15，填 1 會被擋）＋公版 6 個，**不可開隔日到貨**（蝦皮規定選了較長備貨就不能勾）。
    - ⚠️ 隔日到貨頻道還沒用上架檔實傳過，下一版產出先傳 1~2 支確認有吃進去。
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
