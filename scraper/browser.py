import asyncio
import json
import random
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from config.settings import (
    BROWSER_TIMEOUT,
    COOKIE_PATH,
    DELAY_MAX,
    DELAY_MIN,
    HEADLESS,
    MAX_RETRIES,
    USER_AGENT,
)

_playwright = None
_browser: Optional[Browser] = None


async def get_browser() -> Browser:
    global _playwright, _browser
    if _browser is None or not _browser.is_connected():
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
    return _browser


async def create_context() -> BrowserContext:
    browser = await get_browser()
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )

    # Remove navigator.webdriver fingerprint
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en'],
        });
        window.chrome = {
            runtime: {},
        };
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)

    await _inject_cookies(context)
    return context


async def _inject_cookies(context: BrowserContext) -> None:
    cookie_path = Path(COOKIE_PATH)
    if not cookie_path.exists():
        logger.debug("Cookie file not found, skipping injection")
        return

    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)

        if not cookies:
            logger.debug("Cookie file is empty, skipping injection")
            return

        await context.add_cookies(cookies)
        logger.info(f"Injected {len(cookies)} cookies")
    except Exception as e:
        logger.warning(f"Failed to inject cookies: {e}")


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
