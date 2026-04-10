"""
根據 1688 商品資料 + AI 生成內容，填入蝦皮批次上架 Excel。
"""
import shutil
from pathlib import Path

from loguru import logger

TEMPLATE_PATH = Path(__file__).parent.parent / "config" / "shopee_template.xlsx"

# 蝦皮上傳模板的欄位對應（0-indexed，Row 2 是 header）
# Row 0: internal keys, Row 1: internal data, Row 2: 中文 header, Row 3: 必填/選填, Row 4: 說明
# 資料從 Row 5 開始填
COL = {
    "category": 0,          # A: 分類
    "product_name": 1,      # B: 商品名稱
    "description": 2,       # C: 商品描述
    "min_purchase": 3,      # D: 最低購買數量
    "parent_sku": 4,        # E: 主商品貨號
    "dangerous": 5,         # F: 危險物品
    "var_id": 6,            # G: 商品規格識別碼
    "var_name_1": 7,        # H: 規格名稱 1
    "var_option_1": 8,      # I: 規格選項 1
    "var_image": 9,         # J: 規格圖片
    "var_name_2": 10,       # K: 規格名稱 2
    "var_option_2": 11,     # L: 規格選項 2
    "price": 12,            # M: 價格
    "stock": 13,            # N: 庫存
    "option_sku": 14,       # O: 商品選項貨號
    "size_chart": 15,       # P: 新版尺寸表
    "size_chart_img": 16,   # Q: 圖片尺寸表
    "gtin": 17,             # R: GTIN
    "cover_image": 18,      # S: 主商品圖片
    "image_1": 19,          # T: 商品圖片 1
    "image_2": 20,          # U: 商品圖片 2
    "image_3": 21,          # V: 商品圖片 3
    "image_4": 22,          # W: 商品圖片 4
    "image_5": 23,          # X: 商品圖片 5
    "image_6": 24,          # Y: 商品圖片 6
    "image_7": 25,          # Z: 商品圖片 7
    "image_8": 26,          # AA: 商品圖片 8
    "weight": 27,           # AB: 重量
    "length": 28,           # AC: 長度
    "width": 29,            # AD: 寬度
    "height": 30,           # AE: 高度
    # 31-41: 物流方式 (11 個)
    "pre_order_days": 42,   # AQ: 較長備貨天數
}

# 物流欄位 index（32-42 對應蝦皮的各物流）
LOGISTICS_COLS = list(range(31, 42))

# 蝦皮圖片需要 URL，這裡先用本地路徑佔位
# 實際上蝦皮批次上架需要圖片 URL 或本地路徑（依版本而定）


def generate_shopee_excel(
    product_data: dict,
    ai_content: dict,
    image_paths: dict,
    user_config: dict,
    output_path: Path,
    template_path: Path | None = None,
) -> Path:
    """
    填入蝦皮上傳 Excel。

    Args:
        product_data: 1688 爬取的商品 JSON
        ai_content: AI 生成的 {"title", "description"}
        image_paths: {"main": [path,...], "detail": [path,...], "sku": {name: path}}
        user_config: {
            "category": "蝦皮分類路徑",
            "selling_price": 85,
            "stock_per_option": 5,
            "selected_skus": ["黑", "灰", "粉"],  # 選哪些 SKU
            "weight": 0.1,  # kg
        }
        output_path: 輸出的 Excel 路徑
        template_path: 蝦皮模板路徑（可選）

    Returns:
        輸出的 Excel 路徑
    """
    import pandas as pd

    template = template_path or TEMPLATE_PATH
    if not template.exists():
        logger.error(f"蝦皮模板不存在: {template}")
        raise FileNotFoundError(f"Template not found: {template}")

    # 用 calamine 讀模板前幾行（保留 header）
    df_template = pd.read_excel(template, sheet_name="上傳模板", header=None, engine="calamine")
    header_rows = df_template.iloc[:5].copy()  # 前 5 行是蝦皮的 header/說明

    # 準備商品資料行
    skus = product_data.get("skus", [])
    selected_sku_names = user_config.get("selected_skus", [])

    # 篩選 SKU
    if selected_sku_names:
        selected_skus = [s for s in skus if any(
            sel in str(s.get("attributes", {}).values()) for sel in selected_sku_names
        )]
        if not selected_skus:
            selected_skus = skus[:len(selected_sku_names)]
    else:
        selected_skus = skus

    if not selected_skus:
        # 沒有 SKU，只建一行
        selected_skus = [{"attributes": {}, "price": 0, "stock": 0}]

    item_id = product_data.get("item_id", "unknown")
    title = ai_content.get("title", product_data.get("title", ""))
    description = ai_content.get("description", "")
    selling_price = user_config.get("selling_price", 99)
    stock = user_config.get("stock_per_option", 10)
    weight = user_config.get("weight", 0.1)
    category = user_config.get("category", "")

    # 取圖片路徑
    main_imgs = image_paths.get("main", [])
    sku_imgs = image_paths.get("sku", {})

    # 判斷有沒有規格
    has_variations = len(selected_skus) > 1
    var_name = ""
    if has_variations and selected_skus[0].get("attributes"):
        var_name = list(selected_skus[0]["attributes"].keys())[0]  # 通常是「颜色」
        # 轉台灣用語
        var_name = var_name.replace("颜色", "顏色").replace("尺码", "尺碼").replace("规格", "規格")

    rows = []
    for i, sku in enumerate(selected_skus):
        row = [None] * df_template.shape[1]

        if i == 0:
            # 第一行填完整商品資訊
            row[COL["category"]] = category
            row[COL["product_name"]] = title
            row[COL["description"]] = description
            row[COL["min_purchase"]] = 1
            row[COL["parent_sku"]] = f"1688-{item_id}"
            row[COL["dangerous"]] = "否"

            # 圖片
            if main_imgs:
                row[COL["cover_image"]] = str(main_imgs[0]) if main_imgs else ""
                for j, img in enumerate(main_imgs[1:9]):
                    col_key = f"image_{j+1}"
                    if col_key in COL:
                        row[COL[col_key]] = str(img)

            # 重量尺寸
            row[COL["weight"]] = weight

            # 物流：全部啟用
            for lc in LOGISTICS_COLS:
                row[lc] = "啟用"

        # 每一行都填的欄位
        if has_variations:
            row[COL["var_id"]] = f"1688-{item_id}" if i == 0 else ""
            row[COL["var_name_1"]] = var_name if i == 0 else ""

            # 規格選項
            attr_values = list(sku.get("attributes", {}).values())
            option_name = attr_values[0] if attr_values else f"選項{i+1}"
            # 簡體→繁體基本轉換
            option_name = option_name.replace("颜色", "顏色")
            row[COL["var_option_1"]] = option_name

            # 規格圖片
            sku_img = sku_imgs.get(attr_values[0], "") if attr_values else ""
            row[COL["var_image"]] = str(sku_img) if sku_img else ""

        row[COL["price"]] = selling_price
        row[COL["stock"]] = stock
        row[COL["option_sku"]] = f"{item_id}-{i:03d}"

        rows.append(row)

    # 組合 header + 資料
    df_data = pd.DataFrame(rows, columns=df_template.columns)
    df_output = pd.concat([header_rows, df_data], ignore_index=True)

    # 寫出 Excel
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 直接複製模板然後用 openpyxl 寫入資料行（保持模板格式）
    # 但 openpyxl 解析蝦皮模板有問題，改用 pandas 直接寫
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_output.to_excel(writer, sheet_name="上傳模板", index=False, header=False)

    logger.info(f"蝦皮 Excel 已產生: {output_path} ({len(rows)} 個 SKU)")
    return output_path
