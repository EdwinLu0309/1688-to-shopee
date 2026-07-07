"""
跨平台 Google 登入（Playwright）→ 存 config/google_cookies.json，供抓私有 Google Sheet。

為什麼要這個：
  Windows 的 Chrome 用 App-Bound Encryption（v20）加密 cookie，純 DPAPI 解不開
  （金鑰再被 Chrome 服務包一層，要 SYSTEM 權限）。與其去解密日常 Chrome 的 cookie，
  不如讓使用者用 Playwright 開的瀏覽器登入一次 Google，把 session cookie 存下來重複用
  —— 跟本專案「🔑 登入 1688」完全同一套模式（save_cookies → config/cookies.json）。
  macOS 仍可走 chrome_cookies 的免登入收割（見 sheet_fetcher 多來源 fallback），
  但這條 Playwright 登入路兩個平台都能用，是 Windows 的主力。

用法：
  # 一次性登入（開瀏覽器，登入後自動偵測、存檔）
  await save_google_session(sheet_id, gid)
  # 之後由 sheet_fetcher 讀 config/google_cookies.json 帶進 httpx 抓 gviz CSV
  cookies = load_saved_cookies()
"""
import json
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
GOOGLE_COOKIE_PATH = ROOT / "config" / "google_cookies.json"

# 只留這些網域的 cookie（抓 gviz 需要 google.com / docs.google.com 的 session）
_KEEP_DOMAINS = ("google.com", "docs.google.com")

_STEALTH_KW = {
    "viewport": {"width": 1280, "height": 900},
    "locale": "zh-TW",
}


def _gviz_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"


def _edit_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}"


def _looks_like_csv(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    if head.startswith("<") or "doctype" in head or "accounts.google" in head:
        return False
    return ("," in head) or ("\n" in text)


def load_saved_cookies(cookie_path: Path = GOOGLE_COOKIE_PATH) -> list[dict]:
    """讀先前登入存下的 Google cookie（playwright/httpx 通用 dict 清單）；沒有回 []。"""
    if not cookie_path.exists():
        return []
    try:
        return json.loads(cookie_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"讀 google_cookies.json 失敗：{e}")
        return []


async def _launch(pw, headless: bool):
    """優先用系統真實 Chrome（channel=chrome，Google 較不會擋自動化）；沒有再退回內建 chromium。"""
    args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    try:
        browser = await pw.chromium.launch(channel="chrome", headless=headless, args=args)
        return browser, "chrome"
    except Exception as e:  # noqa: BLE001
        logger.debug(f"channel=chrome 啟動失敗（{e}）→ 退回內建 chromium")
        browser = await pw.chromium.launch(headless=headless, args=args)
        return browser, "chromium"


async def save_google_session(
    sheet_id: str,
    gid: str,
    cookie_path: Path = GOOGLE_COOKIE_PATH,
    timeout_sec: int = 300,
) -> dict:
    """開瀏覽器讓使用者登入 Google，能抓到目標 Sheet 的 gviz CSV 後存 cookie。

    偵測「登入成功」的方式＝直接用瀏覽器 session 試抓 gviz CSV，成功才算數
    （比偵測網址跳轉可靠，因為要的就是「抓得到那張表」）。回傳 {ok, count, browser, error}。
    """
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser, chan = await _launch(pw, headless=False)
    context = await browser.new_context(**_STEALTH_KW)
    await context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    page = await context.new_page()
    logger.info(f"開瀏覽器（{chan}）登入 Google…最多等 {timeout_sec // 60} 分鐘")
    try:
        await page.goto(_edit_url(sheet_id, gid), wait_until="domcontentloaded")
    except Exception:  # noqa: BLE001
        pass

    # 每 3 秒用 context.request 試抓 gviz（共用瀏覽器 cookie）；抓到合法 CSV = 已登入且有權限。
    ok = False
    waited = 0
    while waited < timeout_sec:
        try:
            resp = await context.request.get(_gviz_url(sheet_id, gid), timeout=15000)
            if resp.ok:
                body = await resp.text()
                if _looks_like_csv(body):
                    ok = True
                    break
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(3000)
        waited += 3

    cookies = await context.cookies()
    await browser.close()
    await pw.stop()

    if not ok:
        return {"ok": False, "count": 0, "browser": chan,
                "error": "逾時未偵測到可讀取的 Sheet（沒登入完成，或此帳號沒有名單存取權）"}

    kept = [c for c in cookies if any(d in c.get("domain", "") for d in _KEEP_DOMAINS)]
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"✓ Google 登入完成，存 {len(kept)} 個 cookie → {cookie_path}")
    return {"ok": True, "count": len(kept), "browser": chan, "error": ""}
