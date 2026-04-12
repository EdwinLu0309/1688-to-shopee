import os
from pathlib import Path

from dotenv import load_dotenv

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

# Google Sheet 採購表
GOOGLE_SHEET_ID = "1sujb1icy2CBjMECMIhvCXb2t81zyr-CcmoPhVwEunIM"
GOOGLE_SHEET_GID = "823737836"

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
