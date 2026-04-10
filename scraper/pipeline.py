"""
完整 pipeline: JSON → 下載圖片 → AI 生成內容 → 蝦皮 Excel
"""
import asyncio
import json
from pathlib import Path

from loguru import logger

from config.settings import OUTPUT_DIR, IMAGE_DIR
from scraper.ai_generator import generate_shopee_content
from scraper.downloader import download_product_images_from_json
from scraper.shopee_excel import generate_shopee_excel


async def run_pipeline(
    product_json_path: Path,
    shopee_template_path: Path,
    user_config: dict,
    output_dir: Path | None = None,
) -> dict:
    """
    執行完整 pipeline。

    Args:
        product_json_path: 1688 商品 JSON 路徑
        shopee_template_path: 蝦皮 Excel 模板路徑
        user_config: {
            "category": "蝦皮分類",
            "selling_price": 85,
            "stock_per_option": 5,
            "selected_skus": ["黑", "灰", "粉"],
            "weight": 0.1,
        }
        output_dir: 輸出目錄

    Returns:
        {"excel": path, "images_dir": path, "ai_content": dict}
    """
    # 1. 讀取商品 JSON
    product_data = json.loads(product_json_path.read_text(encoding="utf-8"))
    item_id = product_data.get("item_id", "unknown")
    logger.info(f"Processing item: {item_id} - {product_data.get('title', '')[:30]}")

    out = output_dir or Path(OUTPUT_DIR)
    item_dir = out / item_id
    item_dir.mkdir(parents=True, exist_ok=True)

    # 2. 下載圖片
    logger.info("Step 1: Downloading images...")
    image_paths = await download_product_images_from_json(product_data, item_dir / "images")

    # 3. AI 生成蝦皮內容
    logger.info("Step 2: Generating Shopee content with AI...")
    ai_content = generate_shopee_content(product_data, user_config)
    # 存 AI 結果
    ai_path = item_dir / "ai_content.json"
    ai_path.write_text(json.dumps(ai_content, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4. 生成蝦皮 Excel
    logger.info("Step 3: Generating Shopee Excel...")
    excel_path = item_dir / f"shopee_upload_{item_id}.xlsx"
    generate_shopee_excel(
        product_data=product_data,
        ai_content=ai_content,
        image_paths=image_paths,
        user_config=user_config,
        output_path=excel_path,
        template_path=shopee_template_path,
    )

    result = {
        "excel": excel_path,
        "images_dir": item_dir / "images",
        "ai_content": ai_content,
        "item_id": item_id,
    }

    logger.info(f"Pipeline complete for {item_id}")
    logger.info(f"  Excel: {excel_path}")
    logger.info(f"  Images: {item_dir / 'images'}")
    logger.info(f"  Title: {ai_content.get('title', '')[:50]}")

    return result
