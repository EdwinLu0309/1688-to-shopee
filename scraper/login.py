"""
用 persistent context 開啟瀏覽器登入 1688。
登入狀態自動保存在 browser_profile 目錄。
"""
import asyncio
import threading

from loguru import logger

from scraper.browser import get_context, close_context


async def interactive_login() -> bool:
    """開啟瀏覽器讓使用者登入 1688，自動偵測登入成功後存檔關閉（不需按 Enter）。"""
    context = await get_context()
    page = await context.new_page()

    logger.info("瀏覽器已開啟，請登入 1688 帳號（掃碼或帳號密碼皆可）")
    logger.info("登入成功後會自動偵測並儲存，無需手動操作終端機")

    await page.goto("https://login.1688.com", wait_until="domcontentloaded")

    # 自動輪詢：只認登入後才會出現的 cookie（unb=會員ID、_nk_=暱稱）
    # 注意：_csrf_token 未登入也有，不能當指標
    login_cookies = {"unb", "_nk_"}
    max_wait_seconds = 600  # 最多等 10 分鐘
    interval = 4
    for _ in range(max_wait_seconds // interval):
        await asyncio.sleep(interval)
        try:
            cookies = await context.cookies()
        except Exception:
            break
        names = {c["name"] for c in cookies}
        if names & login_cookies:
            logger.info("偵測到登入成功！正在儲存登入狀態...")
            await asyncio.sleep(2)  # 等 cookie 寫入 profile
            await page.close()
            await close_context()
            logger.info("登入狀態已保存到 browser profile，現在可以用 scrape 抓完整 SKU")
            return True

    logger.error("超時 10 分鐘未偵測到登入，請重試")
    await page.close()
    await close_context()
    return False
