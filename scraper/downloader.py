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


def _guess_ext(url: str, content_type: str) -> str:
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if ext in url.lower() or ext.lstrip(".") in content_type:
            return ext
    return ".jpg"
