# 1688-to-shopee

## 專案簡介
1688 商品資訊爬取 → AI 生成蝦皮文案 → 蝦皮批次上架 Excel 自動產生。

## 技術棧
- Python 3.14
- Playwright（備用，1688 反爬嚴格目前未使用）
- Claude in Chrome MCP（實際爬取方式）
- Anthropic SDK（Claude API，AI 內容生成）
- HTTPX（圖片下載）
- Click（CLI）
- openpyxl / python-calamine（Excel 讀寫）
- Loguru（日誌）
- python-dotenv（環境變數）

## 檔案結構
```
├── main.py                    # CLI 入口（login/scrape/generate）
├── config/
│   ├── settings.py            # 全域設定
│   ├── shopee_template.xlsx   # 蝦皮批次上架模板
│   └── browser_profile/       # Playwright 登入 profile（gitignored）
├── scraper/
│   ├── models.py              # Product1688, SKUOption, PriceRange
│   ├── data_extractor.py      # __INIT_DATA__ 結構化資料提取
│   ├── item_page.py           # Playwright 爬取 + DOM fallback
│   ├── network.py             # XHR 攔截 + SKU 解析
│   ├── browser.py             # Playwright persistent context
│   ├── login.py               # 手動登入模組
│   ├── downloader.py          # 圖片下載（主圖/細節/SKU）
│   ├── ai_generator.py        # Claude API 生成蝦皮標題/描述
│   ├── shopee_excel.py        # 蝦皮 Excel 模板填入
│   └── pipeline.py            # 全流程串接
├── output/                    # 產出目錄（gitignored）
│   └── {item_id}/
│       ├── ai_content.json
│       ├── shopee_upload_{item_id}.xlsx
│       └── images/
│           ├── main/
│           ├── detail/
│           └── sku/
└── logs/                      # 日誌（gitignored）
```

## CLI 指令
```bash
# 登入 1688（Playwright persistent context）
python main.py login

# 爬取單一商品（Playwright）
python main.py scrape "https://detail.1688.com/offer/XXX.html" -v -j

# 從已爬取的 JSON 生成蝦皮上架 Excel
python main.py generate product.json -t config/shopee_template.xlsx -p 85 -s 5
```

## 環境變數
- `ANTHROPIC_API_KEY` — Claude API key（放 .env）

## 爬取方式說明
1688 反爬嚴格（Playwright 即使用 channel="chrome" 仍被偵測），目前實際爬取是透過 Claude in Chrome MCP 在用戶已登入的 Chrome 中執行 JS 提取 DOM。Playwright 相關程式碼保留作為備用。

## AI 生成規則
蝦皮商品描述禁止：產地、出貨速度字眼、導外聯繫、站外交易引導、其他平台名稱、絕對化用語、醫療宣稱。詳見 `ai_generator.py` 的 SYSTEM_PROMPT。

## 圖片後製介面
`downloader.py` 中的 `download_product_images_from_json()` 預留了 TODO 註解，之後接入圖片後製 pipeline。
