import asyncio
from pathlib import Path

import httpx
from loguru import logger

from config.settings import IMAGE_DIR
from scraper.models import Product1688

SEMAPHORE = asyncio.Semaphore(5)
HEADERS = {
    "Referer": "https://detail.1688.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
}


async def download_product_images(product: Product1688) -> dict[str, list[Path]]:
    base = Path(IMAGE_DIR) / product.item_id
    main_dir = base / "main"
    detail_dir = base / "detail"
    main_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        main_tasks = [
            _download_one(client, url, main_dir, f"main_{i:03d}")
            for i, url in enumerate(product.main_images)
        ]
        detail_tasks = [
            _download_one(client, url, detail_dir, f"detail_{i:03d}")
            for i, url in enumerate(product.detail_images)
        ]

        main_results = await asyncio.gather(*main_tasks, return_exceptions=True)
        detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)

    main_paths = [r for r in main_results if isinstance(r, Path)]
    detail_paths = [r for r in detail_results if isinstance(r, Path)]

    logger.info(f"Downloaded {len(main_paths)}/{len(product.main_images)} main images")
    logger.info(f"Downloaded {len(detail_paths)}/{len(product.detail_images)} detail images")

    return {"main": main_paths, "detail": detail_paths}


async def _download_one(
    client: httpx.AsyncClient, url: str, dest_dir: Path, name: str
) -> Path:
    async with SEMAPHORE:
        try:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            ext = _guess_ext(url, content_type)
            path = dest_dir / f"{name}{ext}"
            path.write_bytes(response.content)
            logger.debug(f"Saved: {path}")
            return path
        except Exception as e:
            logger.warning(f"Failed to download {url}: {e}")
            raise


async def download_product_images_from_json(product_data: dict, dest_dir: Path) -> dict:
    """從 JSON 資料下載圖片（不需要 Product1688 model）。"""
    main_dir = dest_dir / "main"
    detail_dir = dest_dir / "detail"
    sku_dir = dest_dir / "sku"
    main_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.mkdir(parents=True, exist_ok=True)
    sku_dir.mkdir(parents=True, exist_ok=True)

    main_urls = product_data.get("main_images", [])
    detail_urls = product_data.get("detail_images", [])
    sku_images = product_data.get("sku_images", {})

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        # 主圖
        main_tasks = [_download_one(client, url, main_dir, f"main_{i:03d}")
                      for i, url in enumerate(main_urls)]
        # 細節圖
        detail_tasks = [_download_one(client, url, detail_dir, f"detail_{i:03d}")
                        for i, url in enumerate(detail_urls)]
        # SKU 圖
        sku_tasks = [_download_one(client, url, sku_dir, f"sku_{i:03d}")
                     for i, (name, url) in enumerate(sku_images.items())]

        main_results = await asyncio.gather(*main_tasks, return_exceptions=True)
        detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)
        sku_results = await asyncio.gather(*sku_tasks, return_exceptions=True)

    main_paths = [r for r in main_results if isinstance(r, Path)]
    detail_paths = [r for r in detail_results if isinstance(r, Path)]
    sku_paths_list = [r for r in sku_results if isinstance(r, Path)]

    # SKU 名稱對應路徑
    sku_path_map = {}
    for (name, _), result in zip(sku_images.items(), sku_results):
        if isinstance(result, Path):
            sku_path_map[name] = result

    logger.info(f"Downloaded: {len(main_paths)} main, {len(detail_paths)} detail, {len(sku_path_map)} SKU images")

    # ── 圖片後製介面（預留） ──
    # TODO: 在這裡接入圖片後製 pipeline
    # processed_main = await process_images(main_paths, style="shopee_main")
    # processed_sku = await process_images(sku_paths_list, style="shopee_sku")

    return {
        "main": main_paths,
        "detail": detail_paths,
        "sku": sku_path_map,
    }


def _guess_ext(url: str, content_type: str) -> str:
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if ext in url.lower() or ext.lstrip(".") in content_type:
            return ext
    return ".jpg"
