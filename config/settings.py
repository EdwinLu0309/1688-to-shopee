import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows 主控台預設 cp950（繁中），輸出中文 / ✓✗ 等符號會 UnicodeEncodeError 直接爆掉。
# 強制 stdout/stderr 走 UTF-8（Py3.7+ reconfigure）。此檔被 main.py 與 gui.py 早期匯入，
# 在任何輸出之前生效。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

COOKIE_PATH = BASE_DIR / "config" / "cookies.json"
BROWSER_PROFILE_DIR = BASE_DIR / "config" / "browser_profile"
OUTPUT_DIR = BASE_DIR / "output"
IMAGE_DIR = BASE_DIR / "output" / "images"
BATCH_OUTPUT_DIR = BASE_DIR / "output" / "batch"
LOG_DIR = BASE_DIR / "logs"

HEADLESS = False
BROWSER_TIMEOUT = 30000
DELAY_MIN = 2.0
DELAY_MAX = 5.0
MAX_RETRIES = 3

# Gemini API
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"

# Google Sheet 採購表（人工用，含超連結 gviz 讀不到）
GOOGLE_SHEET_ID = "1sujb1icy2CBjMECMIhvCXb2t81zyr-CcmoPhVwEunIM"
GOOGLE_SHEET_GID = "823737836"

# 【Lady】AI 上架名單（給 AI 用的調整版：純網址+編號+分類+款式+售價；batch2 --ai-list 讀）
AI_LIST_SHEET_ID = "1D7qBDG3WEeUrMPKa2K3yeqmarJ7aKFDThSaWJBk0wcc"
AI_LIST_SHEET_GID = "0"

# 【Lady】預購商品訂貨表（訂貨系統三分頁：1_訂貨主檔 / 2_每日訂購彙總 / 3_訂單明細）
# join key = 商品選項貨號（蝦皮 O 欄＝編號_顏色（身高款）_尺碼）
ORDER_SHEET_ID = "1CJ4u0Nqds0t2_th-Pu97Df4GEJJi9A5AB1edIpIoIyQ"
ORDER_MASTER_TAB = "1_訂貨主檔"
ORDER_SUMMARY_TAB = "2_每日訂購彙總"
ORDER_DETAIL_TAB = "3_訂單明細"
# 借 inventory-sync 的 SA（需被分享為此表編輯者；SA 無 Drive 容量不能自建檔）
ORDER_SHEET_SA_JSON = os.environ.get(
    "ORDER_SHEET_SA_JSON",
    str(Path.home() / ".config" / "gcloud" / "inventory-sync-493112-6047c28ad2b1.json"),
)

# 【Nail】進貨金額核對表（金流核對）。分頁 1688_DB 存 1688 訂單報表原始資料，
# 各日期核對分頁靠「卖家公司名（廠商）」VLOOKUP 進來。刷新＝重抓 1688 待付款訂單覆蓋 1688_DB。
# SA（同 inventory-sync）需被分享為此表編輯者（已確認有權）。
RECONCILE_SHEET_ID = os.environ.get(
    "RECONCILE_SHEET_ID", "1ctZ4tvp6MpW5VXTODwtzAMjjTWD3nqGlyZGbISoTkNE"
)
RECONCILE_DB_TAB = "1688_DB"

# （中央「1688 訂單資料」檔的做法已棄用：daemon 改直寫各消費表自己的 1688_DB，
#  日期分頁活公式 XLOOKUP 本地 1688_DB，即時生效、免 IMPORTRANGE 授權、免中央檔。）

# 美甲帳號專屬 cookie（與 Lady 的 config/cookies.json 分開，免每次切換帳號重登）
COOKIE_PATH_NAIL = BASE_DIR / "config" / "cookies_nail.json"

# 【Nail】蝦皮數據中心（#S098 每日抓取落地表：商品日報_YYYYMM + 大盤日報_YYYY）
# SA（同 inventory-sync）已分享編輯權。Lady/Baby 之後各建一張，用 SHOPEE_ANALYTICS_SHEET_IDS 加。
#（#S101：三家 cookie 都已登入驗證過各抓各的；Lady/Baby 的 Sheet 待 Edwin 建好填 ID，
#  填了排程就自動納入——`shopee-collect-daily` 是 loop 這個 dict 的已登入賣場。）
_SHOPEE_SHEET_IDS_RAW = {
    "nail": os.environ.get(
        "SHOPEE_ANALYTICS_SHEET_ID_NAIL", "1gsVt4ZDhEExs3aruBRiES8dB-hDPOXCX295OdQBOTPE"
    ),
    "lady": os.environ.get("SHOPEE_ANALYTICS_SHEET_ID_LADY", ""),
    "baby": os.environ.get("SHOPEE_ANALYTICS_SHEET_ID_BABY", ""),
}
# 只保留有填 Sheet ID 的賣場（沒填的還沒建表，不進排程）
SHOPEE_ANALYTICS_SHEET_IDS = {k: v for k, v in _SHOPEE_SHEET_IDS_RAW.items() if v}

# Kkren（巧巧郎集運）中繼表【中繼】巧巧郎出貨狀態；抓已出貨→去重 append 到 Kkren_Data 分頁
# 2-2 到貨表的 Kkren_DB 靠 IMPORTRANGE 此表 Kkren_Data。Kkren 登入態存 config/kkren_state.json。
KKREN_SHEET_ID = os.environ.get("KKREN_SHEET_ID", "181lP-qkX-qu7Vd9FQGs3U452sHdU_-1TjE3khanXRm8")
KKREN_DATA_TAB = "Kkren_Data"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

SKU_API_KEYWORDS = [
    "sku.get",
    "offerdetail",
    "skuGet",
    "offer/get",
    "getPriceForBuyer",
]
