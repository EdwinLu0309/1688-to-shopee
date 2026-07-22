"""蝦皮賣家中心登入（Playwright）→ 存 config/shopee_cookies_{shop}.json。

與 scraper/google_login.py 完全同一套模式：開真實 Chrome 讓使用者登入一次，
用 context.request 實打 API 驗證「真的登入了」才存 cookie（比偵測跳轉可靠）。
之後 shopee_analytics.client.ShopeeDataClient 帶這份 cookie 打 mydata API。

多賣場：nail / lady / baby 各登入一次、各存一份。
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent.parent
SELLER_URL = "https://seller.shopee.tw/"

_STEALTH_KW = {
    "viewport": {"width": 1280, "height": 900},
    "locale": "zh-TW",
}


def cookie_path_for(shop: str) -> Path:
    return ROOT / "config" / f"shopee_cookies_{shop}.json"


async def _launch(pw, headless: bool):
    args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    try:
        browser = await pw.chromium.launch(channel="chrome", headless=headless, args=args)
        return browser, "chrome"
    except Exception as e:  # noqa: BLE001
        logger.debug(f"channel=chrome 啟動失敗（{e}）→ 退回內建 chromium")
        browser = await pw.chromium.launch(headless=headless, args=args)
        return browser, "chromium"


async def _probe_logged_in(context) -> bool:
    """帶目前瀏覽器 cookie 實打 mydata API，code==0 = 已登入。"""
    cookies = {c["name"]: c["value"] for c in await context.cookies()}
    cds = cookies.get("SPC_CDS")
    if not cds:
        return False
    from datetime import datetime

    now = datetime.now()
    start = int(datetime(now.year, now.month, now.day).timestamp())
    try:
        resp = await context.request.get(
            f"{SELLER_URL}api/mydata/v3/dashboard/key-metrics/",
            params={"SPC_CDS": cds, "SPC_CDS_VER": "2", "period": "real_time",
                    "start_time": str(start), "end_time": str(start + 86399),
                    "fetag": "fetag"},
            timeout=15000,
        )
        if not resp.ok:
            return False
        body = await resp.json()
        return body.get("code") == 0
    except Exception:  # noqa: BLE001
        return False


async def save_shopee_session(shop: str, timeout_sec: int = 300) -> dict:
    """開瀏覽器讓使用者登入蝦皮賣家中心（指定賣場帳號），驗證後存 cookie。"""
    from playwright.async_api import async_playwright

    path = cookie_path_for(shop)
    pw = await async_playwright().start()
    browser, chan = await _launch(pw, headless=False)
    context = await browser.new_context(**_STEALTH_KW)
    await context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    page = await context.new_page()
    logger.info(f"開瀏覽器（{chan}）登入蝦皮賣家中心（{shop} 帳號）…最多等 {timeout_sec // 60} 分鐘")
    try:
        await page.goto(SELLER_URL, wait_until="domcontentloaded")
    except Exception:  # noqa: BLE001
        pass

    ok = False
    waited = 0
    while waited < timeout_sec:
        if await _probe_logged_in(context):
            ok = True
            break
        await page.wait_for_timeout(3000)
        waited += 3

    cookies = await context.cookies()
    await browser.close()
    await pw.stop()

    if not ok:
        return {"ok": False, "count": 0, "browser": chan,
                "error": "逾時未偵測到登入（沒完成登入或帳號沒有數據中心權限）"}

    kept = [c for c in cookies if "shopee" in c.get("domain", "")]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"✓ 蝦皮登入完成（{shop}），存 {len(kept)} 個 cookie → {path}")
    return {"ok": True, "count": len(kept), "browser": chan, "error": ""}
