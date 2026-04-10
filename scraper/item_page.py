import asyncio
import json
import re
from typing import Optional
from urllib.parse import urlparse

from loguru import logger

from config.settings import MAX_RETRIES
from scraper.browser import get_context, close_context, random_delay, safe_goto
from scraper.models import Product1688, SKUOption
from scraper.network import SKUInterceptor, parse_sku_from_api
from scraper import data_extractor


def _extract_item_id(url: str) -> str:
    match = re.search(r"/offer/(\d+)", url)
    if match:
        return match.group(1)
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    return parts[-1].replace(".html", "") if parts else "unknown"


async def scrape_item(url: str) -> Optional[Product1688]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Scraping {url} (attempt {attempt}/{MAX_RETRIES})")
            product = await _scrape_once(url)
            if product:
                return product
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                await random_delay()
    return None


async def _scrape_once(url: str) -> Optional[Product1688]:
    item_id = _extract_item_id(url)
    context = await get_context()
    page = await context.new_page()
    interceptor = SKUInterceptor()

    try:
        await interceptor.attach(page)
        success = await safe_goto(page, url)
        if not success:
            return None

        await asyncio.sleep(2)
        await scroll_to_load_images(page)

        # ── 1. 讀取 __INIT_DATA__ ──
        init_data = await data_extractor.fetch_init_data(page)

        # ── 2. XHR SKU 資料 ──
        raw_sku_data = interceptor.get_best_sku_data()
        await interceptor.detach(page)

        # ── 3. 從 init_data 提取（有就用，沒有 fallback DOM） ──

        # Title
        title = ""
        if init_data:
            title = data_extractor.extract_title(init_data)
        if not title:
            title = await extract_title_dom(page)

        # Description
        description = ""
        if init_data:
            description = data_extractor.extract_description(init_data)

        # Main images
        main_images = []
        if init_data:
            main_images = data_extractor.extract_main_images(init_data)
        if not main_images:
            main_images = await extract_main_images_dom(page)

        # Detail images
        detail_images = []
        if init_data:
            detail_images = data_extractor.extract_detail_images(init_data)
        if not detail_images:
            detail_images = await extract_detail_images_dom(page)

        # SKUs: XHR first, then init_data, then DOM
        skus = []
        if raw_sku_data:
            skus = parse_sku_from_api(raw_sku_data)
        if not skus and init_data:
            skus = parse_sku_from_api(init_data)
        if not skus:
            logger.info("Falling back to DOM for SKUs")
            skus = await extract_skus_from_dom(page)

        # Price ranges
        price_ranges = []
        if init_data:
            price_ranges = data_extractor.extract_price_ranges(init_data)

        # Product attributes
        attributes = {}
        if init_data:
            attributes = data_extractor.extract_attributes(init_data)
        if not attributes:
            attributes = await extract_attributes_dom(page)

        # SKU images
        sku_images = {}
        if init_data:
            sku_images = data_extractor.extract_sku_images(init_data)

        # Video
        video_url = ""
        if init_data:
            video_url = data_extractor.extract_video_url(init_data)
        if not video_url:
            video_url = await extract_video_dom(page)

        # Shop info
        shop_name = ""
        shop_url = ""
        shop_location = ""
        shop_ratings = {}
        if init_data:
            shop_info = data_extractor.extract_shop_info(init_data)
            shop_name = shop_info.get("name", "")
            shop_url = shop_info.get("url", "")
            shop_location = shop_info.get("location", "")
            shop_ratings = {k: v for k, v in shop_info.items()
                           if k.startswith("rating_")}
        if not shop_name:
            shop_name = await extract_shop_name_dom(page)

        # Min order
        min_order = 1
        if init_data:
            min_order = data_extractor.extract_min_order(init_data)
        if min_order <= 1:
            dom_moq = await extract_min_order_dom(page)
            if dom_moq > 1:
                min_order = dom_moq

        # Categories
        categories = []
        if init_data:
            categories = data_extractor.extract_categories(init_data)
        if not categories:
            categories = await extract_categories_dom(page)

        # Origin price
        origin_price = 0.0
        if init_data:
            origin_price = data_extractor.extract_origin_price(init_data)

        product = Product1688(
            item_id=item_id,
            title=title,
            description=description,
            main_images=main_images,
            detail_images=detail_images,
            skus=skus,
            min_order=min_order,
            shop_name=shop_name,
            raw_url=url,
            price_ranges=price_ranges,
            attributes=attributes,
            sku_images=sku_images,
            video_url=video_url,
            shop_url=shop_url,
            shop_location=shop_location,
            shop_ratings=shop_ratings,
            categories=categories,
            origin_price=origin_price,
            raw_sku_data=raw_sku_data,
            raw_init_data=init_data,
        )
        return product

    finally:
        await page.close()


# ══════════════════════════════════════════════════════════════════════
# DOM Fallback Functions
# ══════════════════════════════════════════════════════════════════════

async def scroll_to_load_images(page) -> None:
    logger.debug("Scrolling to trigger lazy-load images")
    try:
        height = await page.evaluate("document.body.scrollHeight")
        steps = 8
        for i in range(1, steps + 1):
            pos = int(height * i / steps)
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await asyncio.sleep(0.4)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception as e:
        logger.debug(f"Scroll error (non-fatal): {e}")


async def extract_title_dom(page) -> str:
    selectors = [
        "h1.product-title",
        "h1[class*='title']",
        ".offer-title h1",
        "h1",
        "[class*='title'] h1",
        ".product-name",
        "#mod-detail-title h1",
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                if text:
                    logger.debug(f"Title from DOM: {sel}")
                    return text
        except Exception:
            pass
    logger.warning("Could not extract title from DOM")
    return ""


async def extract_main_images_dom(page) -> list[str]:
    selectors = [
        ".detail-gallery-turn-wrapper img",
        ".img-tag-main img",
        ".image-gallery img",
        "[class*='gallery'] img",
        "[class*='mainImg'] img",
        ".product-image img",
    ]
    images = []
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                src = await el.get_attribute("src") or await el.get_attribute("data-src") or ""
                src = _normalize_image_url(src)
                if src and src not in images:
                    images.append(src)
            if images:
                logger.debug(f"Main images from DOM: {sel} ({len(images)})")
                break
        except Exception:
            pass
    logger.info(f"Main images (DOM): {len(images)}")
    return images


async def extract_detail_images_dom(page) -> list[str]:
    selectors = [
        ".detail-desc img",
        ".mod-detail-richtext img",
        "[class*='desc'] img",
        "[class*='detail'] img",
        ".content-detail img",
    ]
    images = []
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                src = await el.get_attribute("src") or await el.get_attribute("data-src") or ""
                src = _normalize_image_url(src)
                if src and src not in images:
                    images.append(src)
            if images:
                logger.debug(f"Detail images from DOM: {sel} ({len(images)})")
                break
        except Exception:
            pass
    logger.info(f"Detail images (DOM): {len(images)}")
    return images


async def extract_shop_name_dom(page) -> str:
    selectors = [
        ".shop-name",
        "[class*='shopName']",
        ".seller-name a",
        ".company-name",
        "[class*='company'] a",
        ".supplier-name",
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                if text:
                    return text
        except Exception:
            pass
    return ""


async def extract_min_order_dom(page) -> int:
    selectors = [
        ".min-order",
        "[class*='minOrder']",
        ".trade-number",
        ".moq",
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                nums = re.findall(r"\d+", text)
                if nums:
                    return int(nums[0])
        except Exception:
            pass
    return 1


async def extract_skus_from_dom(page) -> list[SKUOption]:
    js_vars = [
        "window.__INIT_DATA__",
        "window.g_page_config",
        "window.__pageData__",
        "window.detailData",
    ]
    for var in js_vars:
        try:
            data = await page.evaluate(
                f"() => {{ try {{ return {var}; }} catch(e) {{ return null; }} }}"
            )
            if data:
                skus = parse_sku_from_api(data)
                if skus:
                    logger.info(f"DOM SKUs from {var}: {len(skus)}")
                    return skus
        except Exception:
            pass

    # Try <script> tags
    try:
        scripts = await page.query_selector_all("script:not([src])")
        for script in scripts:
            text = await script.inner_text()
            match = re.search(r'"skuInfos"\s*:\s*(\[.+?\])', text, re.DOTALL)
            if match:
                try:
                    sku_infos = json.loads(match.group(1))
                    skus = parse_sku_from_api({"skuInfos": sku_infos})
                    if skus:
                        logger.info(f"DOM SKUs from script tag: {len(skus)}")
                        return skus
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Script tag extraction failed: {e}")

    logger.warning("Could not extract SKUs from DOM")
    return []


async def extract_attributes_dom(page) -> dict[str, str]:
    """從 DOM 提取商品屬性表格。"""
    selectors = [
        ".detail-attributes-list li",
        "[class*='attribute'] li",
        ".product-attr li",
        ".obj-content .obj-sku tr",
    ]
    attrs = {}
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                text = (await el.inner_text()).strip()
                if ":" in text or "：" in text:
                    sep = "：" if "：" in text else ":"
                    k, _, v = text.partition(sep)
                    k, v = k.strip(), v.strip()
                    if k and v:
                        attrs[k] = v
            if attrs:
                logger.debug(f"Attributes from DOM: {sel} ({len(attrs)})")
                break
        except Exception:
            pass
    return attrs


async def extract_video_dom(page) -> str:
    """從 DOM 提取影片 URL。"""
    selectors = [
        "video source",
        "video",
        "[class*='video'] video",
        "[class*='Video'] video",
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                src = (await el.get_attribute("src")
                       or await el.get_attribute("data-src") or "")
                if src:
                    src = _normalize_image_url(src)
                    if src:
                        logger.debug(f"Video from DOM: {sel}")
                        return src
        except Exception:
            pass
    return ""


async def extract_categories_dom(page) -> list[str]:
    """從麵包屑導航提取分類。"""
    selectors = [
        ".bread-crumb a",
        "[class*='breadcrumb'] a",
        ".crumb a",
        ".category-path a",
    ]
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            cats = []
            for el in els:
                text = (await el.inner_text()).strip()
                if text and text not in ("首页", "首頁", "1688.com"):
                    cats.append(text)
            if cats:
                logger.debug(f"Categories from DOM: {sel}")
                return cats
        except Exception:
            pass
    return []


def _normalize_image_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return ""
    url = re.sub(r"_\d+x\d+\.", "_", url)
    return url
