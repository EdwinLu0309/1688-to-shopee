"""
批次 Pipeline：從採購表批次處理所有商品。
讀表 → 逐一處理（下載圖 → Gemini 文案 → Gemini 生圖）→ 組裝蝦皮 Excel
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from config.settings import BATCH_OUTPUT_DIR
from scraper.downloader import download_product_images_from_json
from scraper.gemini_generator import generate_shopee_content, generate_ecommerce_images
from scraper.sheet_reader import SheetProduct, read_procurement_sheet
from scraper.shopee_excel import generate_batch_shopee_excel


async def process_single_product(
    sheet_product: SheetProduct,
    product_data: dict,
    item_output_dir: Path,
) -> dict:
    """
    處理單一商品：下載圖片 → Gemini 文案 → Gemini 生圖。

    Returns:
        {
            "item_id": str,
            "product_data": dict,
            "ai_content": {"title": ..., "description": ...},
            "image_paths": {"main": [...], "detail": [...], "sku": {...}},
            "generated_images": [Path, ...],
            "user_config": dict,
        }
    """
    item_id = sheet_product.item_id
    images_dir = item_output_dir / "images"

    # 1. 下載 1688 圖片
    logger.info(f"[{item_id}] 下載圖片...")
    image_paths = await download_product_images_from_json(product_data, images_dir)

    # 2. Gemini 生成蝦皮文案（多模態：送圖+文）
    logger.info(f"[{item_id}] Gemini 生成文案...")
    user_config = {
        "category": sheet_product.category,
        "selling_price": sheet_product.selling_price,
        "stock_per_option": sheet_product.qty_per_unit,
        "weight": 0.1,
    }

    main_images = image_paths.get("main", [])
    ai_content = generate_shopee_content(
        product_data=product_data,
        image_paths=main_images,
        user_config=user_config,
    )

    # 存 AI 結果
    ai_path = item_output_dir / "ai_content.json"
    ai_path.write_text(
        json.dumps(ai_content, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 3. Gemini 生成電商圖片
    generated_images = []
    title = ai_content.get("title", "")
    description = ai_content.get("description", "")

    if title and main_images:
        logger.info(f"[{item_id}] Gemini 生成電商圖片...")
        generated_dir = images_dir / "generated"
        generated_images = generate_ecommerce_images(
            image_paths=main_images,
            title=title,
            description=description,
            output_dir=generated_dir,
        )
    else:
        logger.warning(f"[{item_id}] 缺少標題或圖片，跳過圖片生成")

    return {
        "item_id": item_id,
        "product_data": product_data,
        "ai_content": ai_content,
        "image_paths": image_paths,
        "generated_images": generated_images,
        "user_config": user_config,
    }


async def run_batch_pipeline(
    sheet_path: Path,
    shopee_template_path: Path,
    json_dir: Path,
    output_dir: Path | None = None,
    force: bool = False,
) -> dict:
    """
    批次處理所有商品。

    Args:
        sheet_path: 採購表 .xlsx 路徑
        shopee_template_path: 蝦皮 Excel 模板路徑
        json_dir: pre-scraped JSON 目錄（{item_id}.json）
        output_dir: 輸出目錄（預設 output/batch_{timestamp}）
        force: 是否強制重新處理已完成的商品

    Returns:
        {
            "output_dir": Path,
            "excel_path": Path,
            "total": int,
            "success": int,
            "skipped": int,
            "failed": int,
            "failures": [{"item_id": str, "error": str}, ...],
        }
    """
    # 讀取採購表
    exchange_rate, products = read_procurement_sheet(sheet_path)
    logger.info(f"採購表共 {len(products)} 筆商品，匯率 {exchange_rate}")

    if not products:
        logger.warning("採購表中沒有有效商品")
        return {"total": 0, "success": 0, "skipped": 0, "failed": 0, "failures": []}

    # 建立輸出目錄
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(BATCH_OUTPUT_DIR) / f"batch_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    failures = []
    skipped = 0

    for i, product in enumerate(products, 1):
        item_id = product.item_id
        logger.info(f"\n{'='*60}")
        logger.info(f"[{i}/{len(products)}] 處理: {product.product_name} (item_id: {item_id})")
        logger.info(f"{'='*60}")

        item_output_dir = output_dir / item_id
        item_output_dir.mkdir(parents=True, exist_ok=True)

        # Resume: 如果已處理過且不是 force 模式，跳過
        ai_cache = item_output_dir / "ai_content.json"
        if ai_cache.exists() and not force:
            logger.info(f"[{item_id}] 已處理過，跳過（使用 --force 可重新處理）")
            # 載入快取的結果
            try:
                cached_ai = json.loads(ai_cache.read_text(encoding="utf-8"))
                if cached_ai.get("title"):
                    skipped += 1
                    # 仍然加入結果，用於 Excel 組裝
                    results.append({
                        "item_id": item_id,
                        "product_data": _load_json(json_dir, item_id),
                        "ai_content": cached_ai,
                        "image_paths": _scan_existing_images(item_output_dir / "images"),
                        "generated_images": _scan_generated_images(item_output_dir / "images" / "generated"),
                        "user_config": {
                            "category": product.category,
                            "selling_price": product.selling_price,
                            "stock_per_option": product.qty_per_unit,
                            "weight": 0.1,
                        },
                    })
                    continue
            except Exception:
                pass  # 快取損壞，重新處理

        # 找 pre-scraped JSON
        product_data = _load_json(json_dir, item_id)
        if product_data is None:
            logger.warning(f"[{item_id}] 找不到 pre-scraped JSON，跳過")
            failures.append({"item_id": item_id, "name": product.product_name, "error": "找不到 JSON"})
            continue

        # 處理商品
        try:
            result = await process_single_product(product, product_data, item_output_dir)
            results.append(result)
            logger.info(f"[{item_id}] 處理完成 ✓")
        except Exception as e:
            logger.error(f"[{item_id}] 處理失敗: {e}")
            failures.append({"item_id": item_id, "name": product.product_name, "error": str(e)})

    # 組裝批次蝦皮 Excel
    success_count = len(results)
    if results:
        logger.info(f"\n組裝蝦皮批次上架 Excel（{success_count} 個商品）...")
        excel_path = output_dir / "shopee_upload.xlsx"
        generate_batch_shopee_excel(
            products=results,
            output_path=excel_path,
            template_path=shopee_template_path,
        )
        logger.info(f"蝦皮 Excel: {excel_path}")
    else:
        excel_path = None
        logger.warning("沒有成功處理的商品，不產生 Excel")

    # 摘要
    summary = {
        "output_dir": output_dir,
        "excel_path": excel_path,
        "total": len(products),
        "success": success_count,
        "skipped": skipped,
        "failed": len(failures),
        "failures": failures,
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"批次處理完成")
    logger.info(f"  總計: {summary['total']} | 成功: {summary['success']} | "
                f"跳過: {summary['skipped']} | 失敗: {summary['failed']}")
    if failures:
        logger.info("失敗清單:")
        for f in failures:
            logger.info(f"  - {f['name']} ({f['item_id']}): {f['error']}")
    logger.info(f"{'='*60}")

    return summary


def _load_json(json_dir: Path, item_id: str) -> dict | None:
    """嘗試載入 pre-scraped JSON。"""
    # 嘗試多種檔名格式
    candidates = [
        json_dir / f"{item_id}.json",
        json_dir / item_id / f"{item_id}.json",
        json_dir / item_id / "product.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"JSON 讀取失敗 {path}: {e}")
    return None


def _scan_existing_images(images_dir: Path) -> dict:
    """掃描已存在的圖片目錄。"""
    result = {"main": [], "detail": [], "sku": {}}
    if not images_dir.exists():
        return result

    main_dir = images_dir / "main"
    if main_dir.exists():
        result["main"] = sorted(main_dir.glob("*.*"))

    detail_dir = images_dir / "detail"
    if detail_dir.exists():
        result["detail"] = sorted(detail_dir.glob("*.*"))

    sku_dir = images_dir / "sku"
    if sku_dir.exists():
        for f in sorted(sku_dir.glob("*.*")):
            result["sku"][f.stem] = f

    return result


def _scan_generated_images(generated_dir: Path) -> list[Path]:
    """掃描已生成的電商圖片。"""
    if not generated_dir.exists():
        return []
    return sorted(generated_dir.glob("generated_*.*"))
