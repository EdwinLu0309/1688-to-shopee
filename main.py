import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import click
from loguru import logger

from config.settings import LOG_DIR
from scraper.item_page import scrape_item


def setup_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, colorize=True, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"scraper_{date.today().isoformat()}.log"
    logger.add(log_file, level="DEBUG", rotation="10 MB", encoding="utf-8")


@click.command()
@click.argument("url")
@click.option("--download-images", "-d", is_flag=True, help="Download product images")
@click.option("--save-json", "-j", is_flag=True, help="Save product data as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(url: str, download_images: bool, save_json: bool, verbose: bool) -> None:
    """Scrape a 1688 product page."""
    setup_logging(verbose)
    asyncio.run(_run(url, download_images, save_json))


async def _run(url: str, download_images: bool, save_json: bool) -> None:
    logger.info(f"Starting scrape: {url}")
    product = await scrape_item(url)

    if not product:
        logger.error("Failed to scrape product")
        sys.exit(1)

    # Display results
    click.echo("")
    click.echo(f"  商品 ID   : {product.item_id}")
    click.echo(f"  標題      : {product.title}")
    click.echo(f"  店鋪      : {product.shop_name}")
    click.echo(f"  最小訂購量 : {product.min_order}")
    click.echo(f"  主圖數量  : {len(product.main_images)}")
    click.echo(f"  細節圖數量 : {len(product.detail_images)}")
    click.echo(f"  SKU 數量  : {len(product.skus)}")
    click.echo("")

    if product.skus:
        click.echo("  SKU 列表:")
        for i, sku in enumerate(product.skus[:20], 1):
            attrs_str = ", ".join(f"{k}={v}" for k, v in sku.attributes.items()) or "（無屬性）"
            click.echo(f"    [{i:02d}] id={sku.sku_id}  屬性={attrs_str}  價格=¥{sku.price:.2f}  庫存={sku.stock}")
        if len(product.skus) > 20:
            click.echo(f"    ... 共 {len(product.skus)} 筆 SKU")
    else:
        click.echo("  SKU: 未抓到")

    if download_images:
        from scraper.downloader import download_product_images
        logger.info("Downloading images...")
        paths = await download_product_images(product)
        click.echo(f"\n  已下載主圖: {len(paths['main'])} 張")
        click.echo(f"  已下載細節圖: {len(paths['detail'])} 張")

    if save_json:
        from config.settings import OUTPUT_DIR
        out_dir = Path(OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{product.item_id}.json"
        data = {
            "item_id": product.item_id,
            "title": product.title,
            "shop_name": product.shop_name,
            "min_order": product.min_order,
            "main_images": product.main_images,
            "detail_images": product.detail_images,
            "skus": [
                {
                    "sku_id": s.sku_id,
                    "attributes": s.attributes,
                    "price": s.price,
                    "stock": s.stock,
                }
                for s in product.skus
            ],
        }
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        click.echo(f"\n  JSON 已儲存: {out_path}")


if __name__ == "__main__":
    main()
