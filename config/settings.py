from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

COOKIE_PATH = BASE_DIR / "config" / "cookies.json"
BROWSER_PROFILE_DIR = BASE_DIR / "config" / "browser_profile"
OUTPUT_DIR = BASE_DIR / "output"
IMAGE_DIR = BASE_DIR / "output" / "images"
LOG_DIR = BASE_DIR / "logs"

HEADLESS = False
BROWSER_TIMEOUT = 30000
DELAY_MIN = 2.0
DELAY_MAX = 5.0
MAX_RETRIES = 3

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
