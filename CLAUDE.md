# 1688-to-shopee

## 專案簡介
1688 商品資訊爬取 → AI 生成蝦皮文案 → 蝦皮批次上架 Excel 自動產生。

## 技術棧
- Python 3.14
- Playwright（備用，1688 反爬嚴格目前未使用）
- Claude in Chrome MCP（實際爬取方式）
- Google Gemini API（google-genai SDK，文案+圖片生成，取代 Claude API）
- Anthropic SDK（Claude API，保留備用）
- HTTPX（圖片下載）
- Click（CLI）
- openpyxl / python-calamine（Excel 讀寫）
- Loguru（日誌）
- python-dotenv（環境變數）

## 檔案結構
```
├── main.py                    # CLI 入口（login/scrape/generate/batch）
├── config/
│   ├── settings.py            # 全域設定（含 Gemini、Google Sheet）
│   ├── shopee_template.xlsx   # 蝦皮批次上架模板
│   └── browser_profile/       # Playwright 登入 profile（gitignored）
├── scraper/
│   ├── models.py              # Product1688, SKUOption, PriceRange
│   ├── extract_1688.js        # ★現行抓取：Chrome MCP 注入此 JS 抽 DOM → 下載 JSON
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

# 從已爬取的 JSON 生成蝦皮上架 Excel（單商品，Claude API）
python main.py generate product.json -t config/shopee_template.xlsx -p 85 -s 5

# 從採購表批次處理（Gemini 文案+生圖 → 蝦皮 Excel）
python main.py batch --sheet procurement.xlsx --json-dir output/ --template config/shopee_template.xlsx

# 批次下載 1688 圖片（讀 Chrome MCP 抓出的 JSON，不經 AI）
python main.py images --ingest-downloads
```

## 抓取流程（現行，2026-06 實測可用）
舊的 `data_extractor.py`（Playwright + `window.__INIT_DATA__`）已失效：現代 1688
detail 頁已無 `__INIT_DATA__`，且 Playwright 會被反爬擋下。現行作法：
1.（一次性）Chrome 設定把 `detail.1688.com` 的「自動下載」設為允許
   （`chrome://settings/content/automaticDownloads`），否則 Blob 下載會被擋。
2. 在已登入的 Chrome 開商品頁，透過 Chrome MCP 注入 `scraper/extract_1688.js`
   → 抽 DOM（主圖/SKU 色卡/細節圖）→ 下載 `{item_id}.json` 到 ~/Downloads。
3. `python main.py images --ingest-downloads` → 搬進 `output/` 並下載所有圖片。

抓取選擇器（寫在 `extract_1688.js`，1688 改版時改這裡）：
- 主圖：`.od-gallery-list img`
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
- `ANTHROPIC_API_KEY` — Claude API key（保留備用）
- `GEMINI_API_KEY` — Google Gemini API key（主要 AI 生成）

## 爬取方式說明
1688 反爬嚴格（Playwright 即使用 channel="chrome" 仍被偵測），目前實際爬取是透過 Claude in Chrome MCP 在用戶已登入的 Chrome 中執行 JS 提取 DOM。Playwright 相關程式碼保留作為備用。

## AI 生成規則
蝦皮商品描述禁止：產地、出貨速度字眼、導外聯繫、站外交易引導、其他平台名稱、絕對化用語、醫療宣稱。詳見 `gemini_generator.py` 的 SHOPEE_SYSTEM_PROMPT（與 `ai_generator.py` 同規則）。

## 蝦皮 Excel 注意事項
- 模板有 7 個 sheet（含隱藏的 HiddenShopBrand、HiddenTax），必須完整保留
- 寫入方式：直接修改模板 zip 中的 sheet2.xml，不用 openpyxl 重建（會破壞 metadata）
- 危險物品欄位值：`Yes`/`No`（不是「是」/「否」）
- 物流欄位值：`開啟`/`關閉`（不是「啟用」/「停用」）
- 圖片必須用 https URL（不能用本地路徑）
- 每個 SKU 行都需要填商品名稱（不能只填第一行）

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
