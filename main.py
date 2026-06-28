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


@cli.command()
@click.option("--sheet", "-s", type=click.Path(exists=True), help="採購表 .xlsx 路徑")
@click.option("--download-sheet", is_flag=True, help="從 Google Sheets 下載採購表")
@click.option("--json-dir", "-j", type=click.Path(exists=True), required=True, help="Pre-scraped JSON 目錄")
@click.option("--template", "-t", type=click.Path(exists=True), required=True, help="蝦皮批次上架 Excel 模板")
@click.option("--output", "-o", type=click.Path(), default=None, help="輸出目錄")
@click.option("--force", is_flag=True, help="重新處理已完成的商品")
@click.pass_context
def batch(ctx: click.Context, sheet: str | None, download_sheet: bool,
          json_dir: str, template: str, output: str | None, force: bool) -> None:
    """從採購表批次處理所有商品（Gemini 文案 + 生圖 → 蝦皮 Excel）。"""
    from scraper.batch_pipeline import run_batch_pipeline

    # 取得採購表
    if download_sheet:
        from config.settings import GOOGLE_SHEET_ID, GOOGLE_SHEET_GID, OUTPUT_DIR
        from scraper.sheet_reader import download_sheet as dl_sheet
        sheet_path = Path(OUTPUT_DIR) / "procurement_sheet.xlsx"
        dl_sheet(GOOGLE_SHEET_ID, GOOGLE_SHEET_GID, sheet_path)
    elif sheet:
        sheet_path = Path(sheet)
    else:
        click.echo("錯誤：請提供 --sheet 或使用 --download-sheet")
        sys.exit(1)

    result = asyncio.run(run_batch_pipeline(
        sheet_path=sheet_path,
        shopee_template_path=Path(template),
        json_dir=Path(json_dir),
        output_dir=Path(output) if output else None,
        force=force,
    ))

    click.echo("")
    click.echo(f"  批次處理完成")
    click.echo(f"  總計: {result['total']} | 成功: {result['success']} | "
               f"跳過: {result['skipped']} | 失敗: {result['failed']}")
    if result.get("excel_path"):
        click.echo(f"  蝦皮 Excel: {result['excel_path']}")
    if result.get("output_dir"):
        click.echo(f"  輸出目錄:   {result['output_dir']}")
    click.echo("")


@cli.command()
@click.option("--json-dir", "-j", type=click.Path(), default="output", help="JSON 目錄（{item_id}.json）")
@click.option("--ingest-downloads", is_flag=True, help="先把 ~/Downloads/*.json 搬進 json-dir")
@click.pass_context
def images(ctx: click.Context, json_dir: str, ingest_downloads: bool) -> None:
    """批次下載 1688 圖片（讀 extract_1688.js 抽出的 JSON，不經 AI）。

    流程：Chrome MCP 注入 scraper/extract_1688.js → JSON 落在 ~/Downloads →
    本指令 --ingest-downloads 搬進 output/ → 逐一下載主圖/細節圖/SKU 圖。
    """
    from scraper.downloader import download_product_images_from_json

    json_path = Path(json_dir)
    json_path.mkdir(parents=True, exist_ok=True)

    # 1. 從 ~/Downloads 搬入抽取器產出的 JSON
    if ingest_downloads:
        downloads = Path.home() / "Downloads"
        moved = 0
        for jf in downloads.glob("*.json"):
            if jf.stem.isdigit():  # 1688 item_id 是純數字
                dest = json_path / jf.name
                jf.replace(dest)
                moved += 1
                click.echo(f"  搬入: {jf.name}")
        click.echo(f"  共搬入 {moved} 個 JSON\n")

    # 2. 逐一商品下載圖片
    json_files = sorted(p for p in json_path.glob("*.json") if p.stem.isdigit())
    if not json_files:
        click.echo(f"  {json_path} 中找不到 {{item_id}}.json，先用 Chrome MCP 抓取")
        sys.exit(1)

    total = {"main": 0, "detail": 0, "sku": 0}
    for jf in json_files:
        data = json.loads(jf.read_text(encoding="utf-8"))
        item_id = data.get("item_id", jf.stem)
        dest = json_path / item_id / "images"
        logger.info(f"[{item_id}] {data.get('title', '')[:30]} 下載圖片...")
        res = asyncio.run(download_product_images_from_json(data, dest))
        n = {"main": len(res["main"]), "detail": len(res["detail"]), "sku": len(res["sku"])}
        for k in total:
            total[k] += n[k]
        click.echo(f"  ✓ {item_id}: 主圖 {n['main']} / 細節 {n['detail']} / SKU {n['sku']}")

    click.echo("")
    click.echo(f"  完成 {len(json_files)} 個商品 | 主圖 {total['main']} / "
               f"細節 {total['detail']} / SKU {total['sku']}")
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
