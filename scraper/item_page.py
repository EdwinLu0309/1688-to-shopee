import asyncio
import json
import re
from typing import Optional
from urllib.parse import urlparse

from loguru import logger

from config.settings import MAX_RETRIES
from scraper.browser import create_context, random_delay, safe_goto
from scraper.models import Product1688, SKUOption
from scraper.network import SKUInterceptor, parse_sku_from_api


def _extract_item_id(url: str) -> str:
    # https://detail.1688.com/offer/736950821906.html
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
    context = await create_context()
    page = await context.new_page()
    interceptor = SKUInterceptor()

    try:
        await interceptor.attach(page)
        success = await safe_goto(page, url)
        if not success:
            return None

        await asyncio.sleep(2)
        await scroll_to_load_images(page)

        raw_sku_data = interceptor.get_best_sku_data()
        await interceptor.detach(page)

        # Parse SKUs: XHR first, fallback to DOM
        skus = []
        if raw_sku_data:
            skus = parse_sku_from_api(raw_sku_data)
        if not skus:
            logger.info("XHR SKU parse empty, falling back to DOM")
            skus = await extract_skus_from_dom(page)

        title = await extract_title(page)
        main_images = await extract_main_images(page)
        detail_images = await extract_detail_images(page)
        shop_name = await extract_shop_name(page)
        min_order = await extract_min_order(page)

        product = Product1688(
            item_id=item_id,
            title=title,
            description="",
            main_images=main_images,
            detail_images=detail_images,
            skus=skus,
            min_order=min_order,
            shop_name=shop_name,
            raw_url=url,
            raw_sku_data=raw_sku_data,
        )
        return product

    finally:
        await page.close()
        await context.close()


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


async def extract_title(page) -> str:
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
                    logger.debug(f"Title found via selector: {sel}")
                    return text
        except Exception:
            pass

    # Fallback: JS variable
    try:
        title = await page.evaluate("""
            () => {
                const d = window.__INIT_DATA__ || window.g_page_config || {};
                return (d.offerDetail && d.offerDetail.subject)
                    || (d.data && d.data.offerInfo && d.data.offerInfo.title)
                    || '';
            }
        """)
        if title:
            return title
    except Exception:
        pass

    logger.warning("Could not extract title")
    return ""


async def extract_main_images(page) -> list[str]:
    selectors_lists = [
        # Thumbnail strip
        ".detail-gallery-turn-wrapper img",
        ".img-tag-main img",
        ".image-gallery img",
        "[class*='gallery'] img",
        "[class*='mainImg'] img",
        ".product-image img",
    ]
    images = []
    for sel in selectors_lists:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                src = await el.get_attribute("src") or await el.get_attribute("data-src") or ""
                src = _normalize_image_url(src)
                if src and src not in images:
                    images.append(src)
            if images:
                logger.debug(f"Main images via selector: {sel} ({len(images)})")
                break
        except Exception:
            pass

    # JS fallback
    if not images:
        try:
            imgs = await page.evaluate("""
                () => {
                    const d = window.__INIT_DATA__ || {};
                    const offer = (d.offerDetail) || (d.data && d.data.offerInfo) || {};
                    return offer.imageList || offer.images || [];
                }
            """)
            if isinstance(imgs, list):
                images = [_normalize_image_url(i) for i in imgs if i]
        except Exception:
            pass

    logger.info(f"Main images: {len(images)}")
    return images


async def extract_detail_images(page) -> list[str]:
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
                logger.debug(f"Detail images via: {sel} ({len(images)})")
                break
        except Exception:
            pass

    logger.info(f"Detail images: {len(images)}")
    return images


async def extract_shop_name(page) -> str:
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

    try:
        name = await page.evaluate("""
            () => {
                const d = window.__INIT_DATA__ || {};
                return (d.sellerInfo && d.sellerInfo.sellerLoginId)
                    || (d.data && d.data.sellerInfo && d.data.sellerInfo.sellerLoginId)
                    || '';
            }
        """)
        if name:
            return name
    except Exception:
        pass

    return ""


async def extract_min_order(page) -> int:
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

    try:
        moq = await page.evaluate("""
            () => {
                const d = window.__INIT_DATA__ || {};
                const offer = (d.offerDetail) || (d.data && d.data.offerInfo) || {};
                return offer.minOrderQuantity || offer.moq || 1;
            }
        """)
        return int(moq)
    except Exception:
        pass

    return 1


async def extract_skus_from_dom(page) -> list[SKUOption]:
    # Try window.__INIT_DATA__ and similar JS globals
    js_vars = [
        "window.__INIT_DATA__",
        "window.g_page_config",
        "window.__pageData__",
        "window.detailData",
    ]
    for var in js_vars:
        try:
            data = await page.evaluate(f"() => {{ try {{ return {var}; }} catch(e) {{ return null; }} }}")
            if data:
                from scraper.network import parse_sku_from_api
                skus = parse_sku_from_api(data)
                if skus:
                    logger.info(f"DOM SKUs from {var}: {len(skus)}")
                    return skus
        except Exception:
            pass

    # Try extracting JSON from <script> tags
    try:
        scripts = await page.query_selector_all("script:not([src])")
        for script in scripts:
            text = await script.inner_text()
            # Look for skuInfos pattern
            match = re.search(r'"skuInfos"\s*:\s*(\[.+?\])', text, re.DOTALL)
            if match:
                try:
                    sku_infos = json.loads(match.group(1))
                    from scraper.network import parse_sku_from_api
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


def _normalize_image_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return ""
    # Remove size constraints for full resolution
    url = re.sub(r"_\d+x\d+\.", "_", url)
    return url
