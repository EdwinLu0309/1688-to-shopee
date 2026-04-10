import asyncio
import random
from typing import Optional

from loguru import logger
from playwright.async_api import BrowserContext, Page, async_playwright

from config.settings import (
    BROWSER_PROFILE_DIR,
    BROWSER_TIMEOUT,
    DELAY_MAX,
    DELAY_MIN,
    MAX_RETRIES,
    USER_AGENT,
)

_playwright = None
_context: Optional[BrowserContext] = None


async def get_context() -> BrowserContext:
    """取得 persistent browser context（共用登入狀態）。"""
    global _playwright, _context
    if _context is not None:
        return _context

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    _playwright = await async_playwright().start()
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_PROFILE_DIR),
        channel="chrome",  # 用系統安裝的 Chrome，不用 Playwright 的 Chromium
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
        user_agent=USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )

    # 移除 webdriver 指紋
    await _context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en'],
        });
        window.chrome = { runtime: {} };
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)

    logger.info(f"Browser profile: {BROWSER_PROFILE_DIR}")
    return _context


async def close_context() -> None:
    """關閉 browser context。"""
    global _playwright, _context
    if _context:
        await _context.close()
        _context = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


async def safe_goto(page: Page, url: str) -> bool:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"Navigating to {url} (attempt {attempt}/{MAX_RETRIES})")
            await page.goto(url, timeout=BROWSER_TIMEOUT, wait_until="domcontentloaded")
            await random_delay()
            return True
        except Exception as e:
            logger.warning(f"Navigation failed (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                delay = random.uniform(DELAY_MIN * 2, DELAY_MAX * 2)
                logger.debug(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {MAX_RETRIES} navigation attempts failed for {url}")
                return False


async def random_delay() -> None:
    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    logger.debug(f"Sleeping {delay:.1f}s")
    await asyncio.sleep(delay)
