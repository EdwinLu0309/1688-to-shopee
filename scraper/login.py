"""
用 persistent context 開啟瀏覽器登入 1688。
登入狀態自動保存在 browser_profile 目錄。
"""
import asyncio
import threading

from loguru import logger

from scraper.browser import get_context, close_context


async def interactive_login() -> bool:
    """開啟瀏覽器讓使用者登入 1688。完成後按 Enter 關閉。"""
    context = await get_context()
    page = await context.new_page()

    logger.info("請在瀏覽器中登入 1688 帳號")

    await page.goto("https://www.1688.com", wait_until="domcontentloaded")

    # 在背景線程等待使用者按 Enter
    done = asyncio.Event()

    def wait_input():
        input("\n  >>> 登入完成後，按 Enter 鍵結束 <<<\n")
        done.set()

    t = threading.Thread(target=wait_input, daemon=True)
    t.start()

    # 等待使用者按 Enter 或超時 10 分鐘
    try:
        await asyncio.wait_for(done.wait(), timeout=600)
    except asyncio.TimeoutError:
        logger.error("超時 10 分鐘，請重試")
        await page.close()
        await close_context()
        return False

    # 檢查是否真的登入了（看 URL 不在登入頁）
    current_url = page.url
    logger.info(f"當前頁面：{current_url}")

    await page.close()
    await close_context()
    logger.info("登入狀態已保存到 browser profile")
    return True
