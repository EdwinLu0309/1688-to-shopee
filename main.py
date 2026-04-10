import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import click
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

from config.settings import LOG_DIR
from scraper.browser import close_context
from scraper.item_page import scrape_item


def setup_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, colorize=True, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"scraper_{date.today().isoformat()}.log"
    logger.add(log_file, level="DEBUG", rotation="10 MB", encoding="utf-8")


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """1688 商品爬蟲工具。"""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@cli.command()
@click.pass_context
def login(ctx: click.Context) -> None:
    """開啟瀏覽器登入 1688，儲存 Cookie。"""
    from scraper.login import interactive_login
    success = asyncio.run(interactive_login())
    if success:
        click.echo("\n  登入成功！Profile 已儲存。現在可以用 scrape 指令爬取商品。")
    else:
        click.echo("\n  登入失敗，請重試。")
        sys.exit(1)


@cli.command()
@click.argument("url")
@click.option("--download-images", "-d", is_flag=True, help="Download product images")
@click.option("--save-json", "-j", is_flag=True, help="Save product data as JSON")
@click.pass_context
def scrape(ctx: click.Context, url: str, download_images: bool, save_json: bool) -> None:
    """爬取 1688 商品頁面。"""
    asyncio.run(_run(url, download_images, save_json))


@cli.command()
@click.argument("product_json", type=click.Path(exists=True))
@click.option("--template", "-t", type=click.Path(exists=True), required=True, help="蝦皮批次上架 Excel 模板")
@click.option("--price", "-p", type=int, required=True, help="台灣售價 (NT$)")
@click.option("--stock", "-s", type=int, default=10, help="每個規格庫存數")
@click.option("--category", "-c", type=str, default="", help="蝦皮分類")
@click.option("--skus", type=str, default="", help="選擇的 SKU（逗號分隔，空=全部）")
@click.option("--weight", "-w", type=float, default=0.1, help="商品重量 (kg)")
@click.pass_context
def generate(ctx: click.Context, product_json: str, template: str, price: int,
             stock: int, category: str, skus: str, weight: float) -> None:
    """從 1688 商品 JSON 生成蝦皮上架 Excel。"""
    from scraper.pipeline import run_pipeline

    user_config = {
        "selling_price": price,
        "stock_per_option": stock,
        "category": category,
        "selected_skus": [s.strip() for s in skus.split(",") if s.strip()] if skus else [],
        "weight": weight,
    }

    result = asyncio.run(run_pipeline(
        product_json_path=Path(product_json),
        shopee_template_path=Path(template),
        user_config=user_config,
    ))

    click.echo("")
    click.echo(f"  ✓ 蝦皮 Excel: {result['excel']}")
    click.echo(f"  ✓ 圖片目錄:   {result['images_dir']}")
    click.echo(f"  ✓ AI 標題:    {result['ai_content'].get('title', '')[:60]}")
    click.echo("")


async def _run(url: str, download_images: bool, save_json: bool) -> None:
    logger.info(f"Starting scrape: {url}")
    product = await scrape_item(url)

    if not product:
        logger.error("Failed to scrape product")
        sys.exit(1)

    # Display results
    click.echo("")
    click.echo(f"  商品 ID    : {product.item_id}")
    click.echo(f"  標題       : {product.title}")
    click.echo(f"  店鋪       : {product.shop_name}")

    if product.shop_location:
        click.echo(f"  店鋪位置   : {product.shop_location}")
    if product.shop_url:
        click.echo(f"  店鋪連結   : {product.shop_url}")

    click.echo(f"  最小訂購量  : {product.min_order}")

    if product.categories:
        click.echo(f"  商品分類   : {' > '.join(product.categories)}")

    if product.origin_price > 0:
        click.echo(f"  參考價     : ¥{product.origin_price:.2f}")

    # Price ranges
    if product.price_ranges:
        click.echo(f"  階梯價格   : ({len(product.price_ranges)} 階)")
        for pr in product.price_ranges:
            max_str = f"-{pr.max_qty}" if pr.max_qty > 0 else "+"
            click.echo(f"    {pr.min_qty}{max_str} 件: ¥{pr.price:.2f}")

    click.echo(f"  主圖數量   : {len(product.main_images)}")
    click.echo(f"  細節圖數量  : {len(product.detail_images)}")

    if product.video_url:
        click.echo(f"  商品影片   : {product.video_url}")

    # Product attributes
    if product.attributes:
        click.echo(f"  商品屬性   : ({len(product.attributes)} 項)")
        for k, v in list(product.attributes.items())[:15]:
            click.echo(f"    {k}: {v}")
        if len(product.attributes) > 15:
            click.echo(f"    ... 共 {len(product.attributes)} 項")

    # Description preview
    if product.description:
        desc_preview = product.description[:100]
        if len(product.description) > 100:
            desc_preview += "..."
        click.echo(f"  商品描述   : {desc_preview}")

    # SKU images
    if product.sku_images:
        click.echo(f"  SKU 圖片   : {len(product.sku_images)} 組")
        for name, url in list(product.sku_images.items())[:5]:
            click.echo(f"    {name}: {url[:60]}...")
        if len(product.sku_images) > 5:
            click.echo(f"    ... 共 {len(product.sku_images)} 組")

    # Shop ratings
    if product.shop_ratings:
        click.echo(f"  店鋪評分   :")
        for k, v in product.shop_ratings.items():
            click.echo(f"    {k.replace('rating_', '')}: {v}")

    click.echo("")

    # SKU list
    click.echo(f"  SKU 數量   : {len(product.skus)}")
    if product.skus:
        click.echo("  SKU 列表:")
        for i, sku in enumerate(product.skus[:20], 1):
            attrs_str = ", ".join(f"{k}={v}" for k, v in sku.attributes.items()) or "（無屬性）"
            img_tag = " [有圖]" if sku.image_url else ""
            click.echo(f"    [{i:02d}] id={sku.sku_id}  屬性={attrs_str}  價格=¥{sku.price:.2f}  庫存={sku.stock}{img_tag}")
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
            "description": product.description,
            "categories": product.categories,
            "shop_name": product.shop_name,
            "shop_url": product.shop_url,
            "shop_location": product.shop_location,
            "shop_ratings": product.shop_ratings,
            "min_order": product.min_order,
            "origin_price": product.origin_price,
            "price_ranges": [
                {"min_qty": pr.min_qty, "max_qty": pr.max_qty, "price": pr.price}
                for pr in product.price_ranges
            ],
            "attributes": product.attributes,
            "main_images": product.main_images,
            "detail_images": product.detail_images,
            "video_url": product.video_url,
            "sku_images": product.sku_images,
            "skus": [
                {
                    "sku_id": s.sku_id,
                    "attributes": s.attributes,
                    "price": s.price,
                    "stock": s.stock,
                    "image_url": s.image_url,
                }
                for s in product.skus
            ],
        }
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        click.echo(f"\n  JSON 已儲存: {out_path}")

    await close_context()


if __name__ == "__main__":
    cli()
