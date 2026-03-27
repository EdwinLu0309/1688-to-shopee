# 1688-to-shopee

Phase 1: 爬取 1688 單品頁的完整商品資料（標題、SKU、圖片）。

## 安裝

```bash
pip install -r requirements.txt
playwright install chromium
```

## 使用方式

```bash
# 基本爬取
python main.py "https://detail.1688.com/offer/736950821906.html"

# 顯示 debug log
python main.py "https://detail.1688.com/offer/736950821906.html" -v

# 同時下載圖片並儲存 JSON
python main.py "https://detail.1688.com/offer/736950821906.html" -d -j
```

## 選項

| 選項 | 說明 |
|------|------|
| `-v` / `--verbose` | 顯示 DEBUG 等級 log |
| `-d` / `--download-images` | 下載商品圖片到 `output/images/` |
| `-j` / `--save-json` | 將商品資料儲存為 JSON |

## Cookie 注入

若需要登入後才能看到完整資料，將 Cookie 貼入 `config/cookies.json`（Netscape/JSON 格式陣列）。

## 輸出結構

```
output/
├── images/
│   └── {item_id}/
│       ├── main/     # 主圖
│       └── detail/   # 細節圖
└── {item_id}.json    # 商品資料 (加 -j 時)
logs/
└── scraper_YYYY-MM-DD.log
```
