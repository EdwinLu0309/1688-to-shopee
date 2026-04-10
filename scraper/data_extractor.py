"""
從 1688 頁面的 window.__INIT_DATA__ 等 JS 全域變數中提取完整商品資訊。
優先從結構化資料提取，比 DOM scraping 更穩定。
"""
import re
from typing import Any, Optional

from loguru import logger

from scraper.models import PriceRange

# JS 全域變數嘗試順序
_JS_GLOBALS = [
    "window.__INIT_DATA__",
    "window.g_page_config",
    "window.__pageData__",
    "window.detailData",
]


async def fetch_init_data(page) -> Optional[dict]:
    """從頁面讀取 __INIT_DATA__ 或類似全域變數。"""
    for var in _JS_GLOBALS:
        try:
            data = await page.evaluate(
                f"() => {{ try {{ return {var}; }} catch(e) {{ return null; }} }}"
            )
            if data and isinstance(data, dict):
                logger.info(f"Got init data from {var} (keys: {list(data.keys())[:10]})")
                return data
        except Exception:
            pass
    logger.warning("No init data found from any JS global")
    return None


def extract_title(data: dict) -> str:
    paths = [
        lambda d: d["data"]["offerInfo"]["title"],
        lambda d: d["offerDetail"]["subject"],
        lambda d: d["data"]["subject"],
        lambda d: d["globalData"]["offerInfo"]["title"],
        lambda d: d["globalData"]["tempModel"]["offerTitle"],
    ]
    return _try_paths(data, paths, "title", "")


def extract_description(data: dict) -> str:
    paths = [
        lambda d: d["data"]["offerInfo"]["description"],
        lambda d: d["offerDetail"]["description"],
        lambda d: d["data"]["description"],
        lambda d: d["globalData"]["offerInfo"]["description"],
    ]
    desc = _try_paths(data, paths, "description", "")
    if desc:
        # 移除 HTML 標籤，取純文字
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
    return desc


def extract_main_images(data: dict) -> list[str]:
    paths = [
        lambda d: d["data"]["offerInfo"]["imageList"],
        lambda d: d["offerDetail"]["imageList"],
        lambda d: d["offerDetail"]["images"],
        lambda d: d["globalData"]["images"],
        lambda d: d["data"]["images"],
        lambda d: d["globalData"]["offerInfo"]["imageList"],
    ]
    imgs = _try_paths(data, paths, "main_images", [])
    if isinstance(imgs, list):
        return [_normalize_img(i) for i in imgs if i]
    return []


def extract_detail_images(data: dict) -> list[str]:
    """從 offerDetail.description 中的 <img> 標籤提取細節圖。"""
    paths = [
        lambda d: d["data"]["offerInfo"]["detailImages"],
        lambda d: d["offerDetail"]["detailImages"],
        lambda d: d["globalData"]["offerInfo"]["detailImages"],
    ]
    imgs = _try_paths(data, paths, "detail_images", [])
    if isinstance(imgs, list) and imgs:
        return [_normalize_img(i) for i in imgs if i]

    # Fallback: 從 description HTML 中提取 img src
    desc_paths = [
        lambda d: d["data"]["offerInfo"]["description"],
        lambda d: d["offerDetail"]["description"],
        lambda d: d["globalData"]["offerInfo"]["description"],
    ]
    desc_html = _try_paths(data, desc_paths, "desc_html", "")
    if desc_html:
        srcs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', desc_html)
        return [_normalize_img(s) for s in srcs if s and "." in s]
    return []


def extract_price_ranges(data: dict) -> list[PriceRange]:
    """提取階梯價格。"""
    paths = [
        lambda d: d["data"]["offerInfo"]["priceRange"],
        lambda d: d["offerDetail"]["priceRange"],
        lambda d: d["globalData"]["offerInfo"]["priceRange"],
        lambda d: d["data"]["priceRange"],
        # 有時叫 priceRanges
        lambda d: d["data"]["offerInfo"]["priceRanges"],
        lambda d: d["offerDetail"]["priceRanges"],
        lambda d: d["globalData"]["offerInfo"]["priceRanges"],
    ]
    raw = _try_paths(data, paths, "price_ranges", None)
    if not raw:
        # 嘗試從 skuInfos 中提取統一價
        return []

    ranges = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                ranges.append(_parse_one_price_range(item))
            elif isinstance(item, list) and len(item) >= 2:
                # [qty, price] format
                try:
                    ranges.append(PriceRange(
                        min_qty=int(item[0]),
                        max_qty=-1,
                        price=float(item[1]),
                    ))
                except (ValueError, TypeError):
                    pass
    elif isinstance(raw, dict):
        # 單一價格區間
        ranges.append(_parse_one_price_range(raw))

    # 修正 max_qty：下一階的 min_qty - 1
    for i in range(len(ranges) - 1):
        if ranges[i].max_qty == -1:
            ranges[i].max_qty = ranges[i + 1].min_qty - 1

    if ranges:
        logger.info(f"Price ranges: {len(ranges)}")
    return ranges


def _parse_one_price_range(item: dict) -> PriceRange:
    min_qty = int(item.get("beginAmount") or item.get("minQuantity")
                  or item.get("beginNum") or item.get("startQuantity") or 1)
    max_qty = int(item.get("endAmount") or item.get("maxQuantity")
                  or item.get("endNum") or -1)
    price = float(str(item.get("price") or item.get("promotionPrice")
                      or item.get("convertedPrice") or 0).replace(",", ""))
    return PriceRange(min_qty=min_qty, max_qty=max_qty, price=price)


def extract_attributes(data: dict) -> dict[str, str]:
    """提取商品規格屬性（材質、重量、尺寸等）。"""
    paths = [
        lambda d: d["data"]["offerInfo"]["productAttribute"],
        lambda d: d["offerDetail"]["productAttribute"],
        lambda d: d["globalData"]["offerInfo"]["productAttribute"],
        lambda d: d["data"]["offerInfo"]["attributes"],
        lambda d: d["offerDetail"]["attributes"],
        lambda d: d["globalData"]["skuModel"]["productAttribute"],
    ]
    raw = _try_paths(data, paths, "attributes", None)
    if not raw:
        return {}

    attrs = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = (item.get("attributeName") or item.get("name")
                        or item.get("attributeNameCN") or "")
                value = (item.get("attributeValue") or item.get("value")
                         or item.get("attributeValueCN") or "")
                if name and value:
                    attrs[name] = value
    elif isinstance(raw, dict):
        attrs = {k: str(v) for k, v in raw.items() if v}

    if attrs:
        logger.info(f"Product attributes: {len(attrs)}")
    return attrs


def extract_sku_images(data: dict) -> dict[str, str]:
    """提取 SKU 選項圖片（如不同顏色對應的圖）。"""
    paths = [
        lambda d: d["data"]["offerInfo"]["skuMap"],
        lambda d: d["offerDetail"]["skuMap"],
        lambda d: d["globalData"]["skuModel"]["skuProps"],
        lambda d: d["data"]["skuProps"],
        lambda d: d["globalData"]["offerInfo"]["skuProps"],
    ]
    raw = _try_paths(data, paths, "sku_images", None)
    if not raw:
        return {}

    images = {}
    if isinstance(raw, list):
        for prop in raw:
            if not isinstance(prop, dict):
                continue
            values = prop.get("value") or prop.get("values") or []
            if isinstance(values, list):
                for v in values:
                    if isinstance(v, dict):
                        name = v.get("name") or v.get("text") or ""
                        img = v.get("imageUrl") or v.get("image") or v.get("imgUrl") or ""
                        if name and img:
                            images[name] = _normalize_img(img)
    elif isinstance(raw, dict):
        for key, val in raw.items():
            if isinstance(val, dict):
                img = val.get("imageUrl") or val.get("image") or ""
                if img:
                    images[key] = _normalize_img(img)

    if images:
        logger.info(f"SKU images: {len(images)}")
    return images


def extract_video_url(data: dict) -> str:
    paths = [
        lambda d: d["data"]["offerInfo"]["videoUrl"],
        lambda d: d["offerDetail"]["videoUrl"],
        lambda d: d["globalData"]["offerInfo"]["videoUrl"],
        lambda d: d["data"]["offerInfo"]["video"]["videoUrl"],
        lambda d: d["offerDetail"]["video"]["videoUrl"],
        lambda d: d["globalData"]["video"]["videoUrl"],
        lambda d: d["data"]["videoInfo"]["videoUrl"],
    ]
    url = _try_paths(data, paths, "video_url", "")
    if url:
        url = _normalize_img(url)  # same protocol fix
    return url


def extract_shop_info(data: dict) -> dict[str, str]:
    """提取店鋪完整資訊。"""
    info = {}

    # Shop name
    name_paths = [
        lambda d: d["data"]["sellerInfo"]["shopName"],
        lambda d: d["sellerInfo"]["shopName"],
        lambda d: d["globalData"]["sellerInfo"]["shopName"],
        lambda d: d["data"]["sellerInfo"]["sellerLoginId"],
        lambda d: d["sellerInfo"]["sellerLoginId"],
        lambda d: d["globalData"]["sellerInfo"]["loginId"],
        lambda d: d["globalData"]["tempModel"]["sellerLoginId"],
    ]
    info["name"] = _try_paths(data, name_paths, "shop_name", "")

    # Shop URL
    url_paths = [
        lambda d: d["data"]["sellerInfo"]["shopUrl"],
        lambda d: d["sellerInfo"]["shopUrl"],
        lambda d: d["globalData"]["sellerInfo"]["shopUrl"],
        lambda d: d["data"]["sellerInfo"]["url"],
        lambda d: d["globalData"]["sellerInfo"]["url"],
    ]
    info["url"] = _try_paths(data, url_paths, "shop_url", "")

    # Location
    loc_paths = [
        lambda d: d["data"]["sellerInfo"]["location"],
        lambda d: d["sellerInfo"]["location"],
        lambda d: d["globalData"]["sellerInfo"]["location"],
        lambda d: d["data"]["sellerInfo"]["city"],
        lambda d: d["sellerInfo"]["city"],
        lambda d: d["globalData"]["sellerInfo"]["city"],
    ]
    location = _try_paths(data, loc_paths, "shop_location", "")
    if not location:
        # 嘗試拼 province + city
        province = _try_paths(data, [
            lambda d: d["data"]["sellerInfo"]["province"],
            lambda d: d["sellerInfo"]["province"],
            lambda d: d["globalData"]["sellerInfo"]["province"],
        ], "", "")
        city = _try_paths(data, [
            lambda d: d["data"]["sellerInfo"]["city"],
            lambda d: d["sellerInfo"]["city"],
            lambda d: d["globalData"]["sellerInfo"]["city"],
        ], "", "")
        if province or city:
            location = f"{province} {city}".strip()
    info["location"] = location

    # Ratings
    rating_paths = [
        lambda d: d["data"]["sellerInfo"]["评价"],
        lambda d: d["globalData"]["sellerInfo"]["评价"],
    ]
    # 通常 ratings 是更複雜的結構，嘗試多種
    for key in ["goodRate", "buyerServiceScore", "tradeScore", "compositeIndex"]:
        try:
            val = _deep_get(data, key)
            if val is not None:
                info[f"rating_{key}"] = str(val)
        except Exception:
            pass

    return info


def extract_categories(data: dict) -> list[str]:
    paths = [
        lambda d: d["data"]["offerInfo"]["categoryPath"],
        lambda d: d["offerDetail"]["categoryPath"],
        lambda d: d["globalData"]["offerInfo"]["categoryPath"],
        lambda d: d["data"]["categoryPath"],
        lambda d: d["globalData"]["categoryInfo"],
    ]
    raw = _try_paths(data, paths, "categories", None)
    if not raw:
        return []

    cats = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name") or item.get("categoryName") or ""
                if name:
                    cats.append(name)
            elif isinstance(item, str):
                cats.append(item)
    elif isinstance(raw, str):
        cats = [c.strip() for c in raw.split(">") if c.strip()]

    if cats:
        logger.info(f"Categories: {' > '.join(cats)}")
    return cats


def extract_min_order(data: dict) -> int:
    paths = [
        lambda d: d["data"]["offerInfo"]["minOrderQuantity"],
        lambda d: d["offerDetail"]["minOrderQuantity"],
        lambda d: d["globalData"]["offerInfo"]["minOrderQuantity"],
        lambda d: d["data"]["offerInfo"]["moq"],
        lambda d: d["offerDetail"]["moq"],
    ]
    val = _try_paths(data, paths, "min_order", 1)
    try:
        return int(val)
    except (ValueError, TypeError):
        return 1


def extract_origin_price(data: dict) -> float:
    paths = [
        lambda d: d["data"]["offerInfo"]["referencePrice"],
        lambda d: d["offerDetail"]["referencePrice"],
        lambda d: d["globalData"]["offerInfo"]["referencePrice"],
        lambda d: d["data"]["offerInfo"]["originalPrice"],
        lambda d: d["offerDetail"]["originalPrice"],
    ]
    val = _try_paths(data, paths, "origin_price", 0)
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


# ── Helpers ──────────────────────────────────────────────────────────

def _try_paths(data: dict, paths: list, field_name: str, default: Any) -> Any:
    for path_fn in paths:
        try:
            val = path_fn(data)
            if val is not None and val != "" and val != []:
                logger.debug(f"Extracted {field_name} via path")
                return val
        except (KeyError, TypeError, IndexError):
            pass
    return default


def _deep_get(obj: Any, target_key: str, depth: int = 0) -> Any:
    if depth > 5:
        return None
    if isinstance(obj, dict):
        if target_key in obj:
            return obj[target_key]
        for v in obj.values():
            result = _deep_get(v, target_key, depth + 1)
            if result is not None:
                return result
    return None


def _normalize_img(url: str) -> str:
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return ""
    return url
