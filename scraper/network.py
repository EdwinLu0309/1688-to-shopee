import json
import re
from typing import Any, Optional

from loguru import logger
from playwright.async_api import Page, Response

from config.settings import SKU_API_KEYWORDS
from scraper.models import SKUOption


class SKUInterceptor:
    def __init__(self):
        self._captured: list[dict] = []
        self._handler = None

    async def attach(self, page: Page) -> None:
        self._handler = self._make_handler()
        page.on("response", self._handler)
        logger.debug("SKU interceptor attached")

    async def detach(self, page: Page) -> None:
        if self._handler:
            page.remove_listener("response", self._handler)
            logger.debug("SKU interceptor detached")

    def _make_handler(self):
        async def handle_response(response: Response):
            url = response.url
            if not any(kw.lower() in url.lower() for kw in SKU_API_KEYWORDS):
                return
            try:
                text = await response.text()
                parsed = _try_parse_json_or_jsonp(text)
                if parsed:
                    logger.debug(f"Captured SKU response from: {url}")
                    self._captured.append({"url": url, "data": parsed})
            except Exception as e:
                logger.debug(f"Failed to parse response from {url}: {e}")

        return handle_response

    def get_best_sku_data(self) -> Optional[dict]:
        if not self._captured:
            return None
        best = max(self._captured, key=lambda x: len(str(x["data"])))
        logger.info(f"Best SKU data from: {best['url']}")
        return best["data"]


def _try_parse_json_or_jsonp(text: str) -> Optional[Any]:
    text = text.strip()
    # Try plain JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try JSONP: callback({...}) or callback([...])
    match = re.match(r"^[a-zA-Z_$][a-zA-Z0-9_$]*\((.+)\);?$", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None


def parse_sku_from_api(raw: Any) -> list[SKUOption]:
    if not raw:
        return []

    sku_infos = _find_sku_infos(raw)
    if not sku_infos:
        logger.debug("No skuInfos found in API response")
        return []

    skus = []
    for info in sku_infos:
        try:
            sku_id = str(info.get("skuId") or info.get("id") or "")
            attrs = _parse_sku_attrs(info)
            price = _extract_price(info)
            stock = int(info.get("canBookCount") or info.get("amountOnSale") or 0)
            skus.append(SKUOption(
                sku_id=sku_id,
                attributes=attrs,
                price=price,
                stock=stock,
            ))
        except Exception as e:
            logger.debug(f"Failed to parse SKU entry: {e}")

    logger.info(f"Parsed {len(skus)} SKUs from API")
    return skus


def _find_sku_infos(raw: Any) -> Optional[list]:
    """Multi-level fallback to locate skuInfos list."""
    paths = [
        lambda d: d["data"]["skuInfos"],
        lambda d: d["result"]["offerInfo"]["skuInfos"],
        lambda d: d["data"]["offerInfo"]["skuInfos"],
        lambda d: d["result"]["skuInfos"],
        lambda d: d["skuInfos"],
        lambda d: d["data"]["skus"],
        lambda d: d["result"]["skus"],
        lambda d: d["skus"],
    ]
    for path_fn in paths:
        try:
            val = path_fn(raw)
            if isinstance(val, list) and val:
                return val
        except Exception:
            pass

    # Deep search for any list with skuId keys
    return _deep_find_sku_list(raw)


def _deep_find_sku_list(obj: Any, depth: int = 0) -> Optional[list]:
    if depth > 6:
        return None
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and ("skuId" in obj[0] or "id" in obj[0]):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _deep_find_sku_list(v, depth + 1)
            if result:
                return result
    return None


def _parse_sku_attrs(info: dict) -> dict[str, str]:
    attrs = {}

    # Format 1: attributes list [{name, value}]
    raw_attrs = info.get("attributes") or info.get("skuAttributes") or []
    if isinstance(raw_attrs, list):
        for attr in raw_attrs:
            if isinstance(attr, dict):
                name = attr.get("attributeName") or attr.get("name") or ""
                value = attr.get("attributeValue") or attr.get("value") or ""
                if name:
                    attrs[name] = value

    # Format 2: specInfo string "colour:red;size:XL"
    if not attrs:
        spec_info = info.get("specInfo") or info.get("spec") or ""
        if spec_info:
            for part in str(spec_info).split(";"):
                if ":" in part:
                    k, _, v = part.partition(":")
                    attrs[k.strip()] = v.strip()

    return attrs


def _extract_price(info: dict) -> float:
    fields = ["price", "promotionPrice", "consignPrice", "salePrice", "originalPrice"]
    for field in fields:
        val = info.get(field)
        if val is not None:
            try:
                price = float(str(val).replace(",", ""))
                if price > 0:
                    return price
            except Exception:
                pass

    # Nested priceInfo
    price_info = info.get("priceInfo") or {}
    if isinstance(price_info, dict):
        for field in fields:
            val = price_info.get(field)
            if val is not None:
                try:
                    return float(str(val).replace(",", ""))
                except Exception:
                    pass
    return 0.0
