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


@cli.command("generate2")
@click.argument("product_json", type=click.Path(exists=True))
@click.option("--code", required=True, help="商品編號（如 P-a1），用於變體命名 + 主商品貨號")
@click.option("--price", "-p", type=int, required=True, help="蝦皮售價 (NT$)")
@click.option("--stock", "-s", type=int, default=10, help="每個 SKU 庫存數")
@click.option("--category", "-c", type=str, default="", help="蝦皮分類 ID（數字，如 100358）")
@click.option("--template", "-t", type=click.Path(exists=True), default=None, help="蝦皮模板（預設 config/shopee_template.xlsx）")
@click.option("--colors", default="", help="挑選的第一軸顏色：逗號分隔，可用 src=乾淨名（如 '米白色【长裤】=米白色,黑色【长裤】=黑色'）；空=全部用 color_map")
@click.option("--sizes", default="", help="挑選的尺碼：逗號分隔；空=全部")
@click.option("--reuse-content", is_flag=True, help="用 output/{item_id}/ai_content.json 快取，不重呼 Claude")
@click.option("--demand", default="", help="訂貨需求脈絡（給文案引擎參考）")
@click.option("--weight", "-w", type=float, default=0.1, help="商品重量 (kg)")
@click.pass_context
def generate2(ctx: click.Context, product_json: str, code: str, price: int, stock: int,
              category: str, template: str | None, colors: str, sizes: str,
              reuse_content: bool, demand: str, weight: float) -> None:
    """二階規格（顏色×尺碼）蝦皮上架 Excel（過審路徑：Claude 文案 + 程式拼變體）。"""
    from config.settings import OUTPUT_DIR
    from scraper.copywriter import generate_listing, build_variants
    from scraper.shopee_excel import generate_two_tier_excel, TEMPLATE_PATH

    product_data = json.loads(Path(product_json).read_text(encoding="utf-8"))
    item_id = product_data.get("item_id", "unknown")
    item_dir = Path(OUTPUT_DIR) / item_id
    item_dir.mkdir(parents=True, exist_ok=True)

    # 1. 文案：優先用快取，否則呼 Claude
    ai_cache = item_dir / "ai_content.json"
    if reuse_content and ai_cache.exists():
        ai_content = json.loads(ai_cache.read_text(encoding="utf-8"))
        click.echo(f"  使用快取文案: {ai_cache}")
    else:
        ai_content = generate_listing(product_data, {
            "code": code, "selling_price": price,
            "demand": demand, "category": category,
        })
        if ai_content.get("error"):
            click.echo(f"  ✗ 文案生成失敗: {ai_content.get('error')}")
            sys.exit(1)
        ai_cache.write_text(json.dumps(ai_content, ensure_ascii=False, indent=2), encoding="utf-8")
        click.echo(f"  ✓ 文案已生成並存檔: {ai_cache}")

    short_name = ai_content.get("product_short_name", "")
    color_map = dict(ai_content.get("color_map", {}))
    size_labels = ai_content.get("size_labels", {})

    # 2. 挑色 + 清名（--colors 可 src=乾淨名 覆寫 color_map）
    if colors:
        selected_colors = []
        for part in colors.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                src, clean = part.split("=", 1)
                src, clean = src.strip(), clean.strip()
                color_map[src] = clean
            else:
                src = part
            selected_colors.append(src)
    else:
        selected_colors = list(color_map.keys())

    # 3. 挑尺碼（空=全部）
    all_sizes = product_data.get("sizes", []) or list(size_labels.keys())
    selected_sizes = [s.strip() for s in sizes.split(",") if s.strip()] if sizes else all_sizes

    variants = build_variants(code, short_name, color_map,
                              selected_colors, size_labels, selected_sizes)

    # 4. 二階 Excel
    tpl = Path(template) if template else TEMPLATE_PATH
    excel_path = item_dir / f"shopee_upload_{code}.xlsx"
    generate_two_tier_excel(
        product_data=product_data,
        ai_content=ai_content,
        variants=variants,
        config={
            "category": category, "selling_price": price,
            "stock_per_option": stock, "weight": weight, "code": code,
        },
        output_path=excel_path,
        template_path=tpl,
    )

    click.echo("")
    click.echo(f"  ✓ 蝦皮 Excel（二階）: {excel_path}")
    click.echo(f"  ✓ 標題: {ai_content.get('title', '')[:60]}")
    click.echo(f"  ✓ 變體: {len(selected_colors)} 色 × {len(selected_sizes)} 尺碼 = {variants.get('sku_count')} SKU")
    if ai_content.get("flags"):
        click.echo(f"  ⚠ flags: {len(ai_content['flags'])} 則（詳見 {ai_cache}）")
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


@cli.command("batch2")
@click.option("--manifest", "-m", type=click.Path(exists=True), default=None, help="批次清單 JSON（見 config/batch_manifest.example.json）")
@click.option("--ai-list", type=click.Path(exists=True), default=None, help="【Lady】AI 上架名單 CSV（Chrome 同源下載）— 自動轉 manifest")
@click.option("--json-dir", "-j", type=click.Path(exists=True), default="output", help="pre-scraped JSON 目錄")
@click.option("--output", "-o", type=click.Path(), default=None, help="合併 Excel 輸出路徑（預設 output/shopee_batch_upload.xlsx）")
@click.option("--template", "-t", type=click.Path(exists=True), default=None, help="蝦皮模板（預設用 manifest.template 或內建）")
@click.option("--video/--no-video", default=True, help="每商品順便合成短影片（預設開；缺圖會先下載）")
@click.option("--video-n", type=int, default=9, help="影片挑幾張圖")
@click.pass_context
def batch2(ctx: click.Context, manifest: str | None, ai_list: str | None, json_dir: str,
           output: str | None, template: str | None, video: bool, video_n: int) -> None:
    """批次過審二階路徑：manifest / AI 名單 → 逐商品 Claude 文案 + 變體（+影片）→ 合併一個蝦皮 Excel。"""
    from scraper.batch_pipeline2 import run_batch_two_tier

    if not manifest and not ai_list:
        click.echo("錯誤：請提供 --manifest 或 --ai-list")
        sys.exit(1)

    products = None
    if ai_list:
        from scraper.ai_list_reader import parse_ai_list_csv
        products = parse_ai_list_csv(Path(ai_list))

    result = run_batch_two_tier(
        manifest_path=Path(manifest) if manifest else None,
        json_dir=Path(json_dir),
        output_path=Path(output) if output else None,
        template_path=Path(template) if template else None,
        make_video=video,
        video_n=video_n,
        products=products,
    )

    click.echo("")
    click.echo(f"  批次完成：{result['success']}/{result['total']} 成功，失敗 {result['failed']}")
    for m in result.get("products", []):
        vtag = f" | 🎬 {m['video']}" if m.get("video") else ""
        click.echo(f"    ✓ {m['code']}: {m['sku_count']} SKU{vtag} | {m['title'][:40]}")
    for f in result.get("failures", []):
        click.echo(f"    ✗ {f['code']}: {f['error']}")
    if result.get("excel_path"):
        click.echo(f"  蝦皮 Excel: {result['excel_path']}")
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


@cli.command("fetch-list")
@click.option("--output", "-o", type=click.Path(), default=None, help="輸出 CSV（預設 input/lady_ai_list.csv）")
@click.option("--profile", default=None, help="指定 Chrome 設定檔（預設自動掃描所有設定檔）")
@click.pass_context
def fetch_list(ctx: click.Context, output: str | None, profile: str | None) -> None:
    """抓私有「AI 上架名單」Google Sheet → CSV（路 B：解密日常 Chrome 的 Google cookie，免登入）。"""
    from scraper.sheet_fetcher import fetch_ai_list

    res = fetch_ai_list(out_path=Path(output) if output else None, profile=profile)
    if res.get("ok"):
        click.echo(f"\n  ✓ 名單已更新（來源 {res['profile']}，{res['bytes']} bytes）\n")
    else:
        click.echo(f"\n  ✗ 抓取失敗：{res.get('error')}\n")
        if res.get("need_login"):
            click.echo("  → 執行：python main.py google-login\n")
        sys.exit(1)


@cli.command("google-login")
@click.pass_context
def google_login(ctx: click.Context) -> None:
    """開瀏覽器登入 Google 一次，存 session 供抓私有「AI 上架名單」（跨平台，Windows 必走這條）。"""
    import asyncio

    from config.settings import AI_LIST_SHEET_GID, AI_LIST_SHEET_ID
    from scraper.google_login import save_google_session

    res = asyncio.run(save_google_session(AI_LIST_SHEET_ID, str(AI_LIST_SHEET_GID)))
    if res.get("ok"):
        click.echo(f"\n  ✓ Google 登入完成（{res['browser']}），存 {res['count']} 個 cookie\n"
                   "    現在可以 python main.py fetch-list 抓名單了\n")
    else:
        click.echo(f"\n  ✗ 登入未完成：{res.get('error')}\n")
        sys.exit(1)


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


@cli.command("order-import")
@click.argument("export_xlsx", type=click.Path(exists=True))
@click.option("--date", "-d", "order_date", default=None, help="訂貨日期 YYYY-MM-DD（預設今天）")
@click.option("--password", "-P", default=None, help="蝦皮匯出檔密碼（有密碼保護時必填）")
@click.option("--commit", is_flag=True, help="真的寫入 Google Sheet（預設 dry-run 只算不寫）")
@click.pass_context
def order_import(ctx: click.Context, export_xlsx: str, order_date: str | None,
                 password: str | None, commit: bool) -> None:
    """匯入蝦皮待出貨匯出 → 訂單明細 + 每日彙總 → 顯示今日訂貨總金額。

    預設 dry-run（只算不寫）；確認無誤後加 --commit 寫入 Google Sheet。
    """
    from scraper.ordering.pipeline import import_orders, format_report

    the_date = order_date or date.today().isoformat()
    result = import_orders(export_xlsx, date=the_date, password=password, commit=commit)
    click.echo("\n" + format_report(result, commit=commit))
    if not commit and result.summary_rows:
        click.echo("\n👉 確認無誤後加 --commit 寫入 Google Sheet")


@cli.command("order-place")
@click.option("--date", "-d", "order_date", default=None, help="訂貨日期 YYYY-MM-DD（預設今天）")
@click.option("--cookie", default=None, help="1688 cookie 路徑（預設 config/cookies.json）")
@click.option("--headless", is_flag=True, help="無頭模式（除錯建議關掉以便手動解驗證碼）")
@click.option("--all", "do_all", is_flag=True, help="含已下單的列一起重跑（預設只跑下單狀態空的）")
@click.pass_context
def order_place(ctx: click.Context, order_date: str | None, cookie: str | None,
                headless: bool, do_all: bool) -> None:
    """讀某日彙總 → 1688 加購物車 → 回寫下單狀態。需先 order-import --commit。"""
    from scraper.ordering.cart_order import run_place_orders

    the_date = order_date or date.today().isoformat()
    cookie_path = cookie or str(Path("config/cookies.json"))
    result = run_place_orders(
        the_date, cookie_path=cookie_path, headless=headless,
        only_unordered=not do_all, callback=lambda m: click.echo(f"  {m}"),
    )
    if not result:
        click.echo("（沒有待下單的項目）")
        return
    click.echo(f"\n下單結果（{the_date}）：")
    for sku, status in result.items():
        click.echo(f"  {status}  {sku}")


@cli.command("order-verify")
@click.option("--date", "-d", "order_date", default=None, help="訂貨日期 YYYY-MM-DD（預設今天）")
@click.option("--cookie", default=None, help="1688 cookie 路徑（預設 config/cookies.json）")
@click.option("--headless", is_flag=True, help="無頭模式")
@click.pass_context
def order_verify(ctx: click.Context, order_date: str | None, cookie: str | None,
                 headless: bool) -> None:
    """核對購物車：讀某日彙總 → 對 1688 購物車比對商品/規格/數量。"""
    import asyncio as _asyncio

    from scraper.ordering.cart_order import build_order_items, verify_cart
    from scraper.ordering.cart_order import _read_summary_rows
    from scraper.ordering.order_sheet import OrderSheet

    the_date = order_date or date.today().isoformat()
    cookie_path = cookie or str(Path("config/cookies.json"))
    sheet = OrderSheet()
    master = sheet.load_master()
    summary_rows = _read_summary_rows(sheet, the_date, only_unordered=False)
    items, _ = build_order_items(summary_rows, master)
    if not items:
        click.echo("（該日沒有可核對的項目）")
        return
    statuses = _asyncio.run(verify_cart(items, cookie_path, headless,
                                        callback=lambda m: click.echo(f"  {m}")))
    idx_to_sku = {it.row_index: it.sku_code for it in items}
    click.echo(f"\n核對結果（{the_date}）：")
    for idx, status in statuses.items():
        click.echo(f"  {status}  {idx_to_sku.get(idx, idx)}")


if __name__ == "__main__":
    cli()
