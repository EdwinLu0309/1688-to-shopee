"""
根據 1688 商品資料 + AI 生成內容，填入蝦皮批次上架 Excel。
直接修改蝦皮原始模板的 zip 結構，保留所有隱藏 sheet 和 metadata。
"""
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

from loguru import logger

TEMPLATE_PATH = Path(__file__).parent.parent / "config" / "shopee_template.xlsx"


def _to_jpg_url(img) -> str:
    """把 1688/alicdn 圖片網址的影像處理後綴去掉，取回原始 JPG/PNG。

    例：
      ...cib.jpg_.webp      -> ...cib.jpg
      ...cib.jpg_400x400.jpg -> ...cib.jpg
    本地路徑或非 http 字串則原樣回傳。
    """
    s = str(img)
    if s.startswith("http"):
        s = re.sub(r"(\.(?:jpe?g|png|gif|bmp))_[^/]*$", r"\1", s, flags=re.IGNORECASE)
    return s

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

    # 取圖片：蝦皮大量上傳需要 https 網址，不能用本地路徑。
    # 優先用 1688 原圖的 https URL，並去掉 webp 後綴轉回 JPG。
    main_imgs = [_to_jpg_url(u) for u in (product_data.get("main_images", []) or image_paths.get("main", []))]
    sku_imgs = product_data.get("sku_images", {}) or image_paths.get("sku", {})

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

        # 每一行都要填的商品基本資訊（蝦皮要求每行都有）
        row[COL["category"]] = category
        row[COL["product_name"]] = title
        row[COL["description"]] = description
        row[COL["min_purchase"]] = 1
        row[COL["parent_sku"]] = f"1688-{item_id}"
        row[COL["dangerous"]] = "否"
        row[COL["weight"]] = weight

        if i == 0:
            # 圖片只填第一行
            if main_imgs:
                row[COL["cover_image"]] = str(main_imgs[0]) if main_imgs else ""
                for j, img in enumerate(main_imgs[1:9]):
                    col_key = f"image_{j+1}"
                    if col_key in COL:
                        row[COL[col_key]] = str(img)

            # 物流：全部啟用
            for lc in LOGISTICS_COLS:
                row[lc] = "啟用"

        # 規格欄位
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
            row[COL["var_image"]] = _to_jpg_url(sku_img) if sku_img else ""

        row[COL["price"]] = selling_price
        row[COL["stock"]] = stock
        row[COL["option_sku"]] = f"{item_id}-{i:03d}"

        rows.append(row)

    # 寫出 Excel — 直接修改模板 zip 中的 sheet XML，保留所有隱藏 sheet 和 metadata
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_to_template(template, output_path, rows, df_template.shape[1])

    logger.info(f"蝦皮 Excel 已產生: {output_path} ({len(rows)} 個 SKU)")
    return output_path


def _find_upload_sheet(template_path: Path) -> str:
    """找出蝦皮模板中「上傳模板」對應的 sheet XML 檔名。"""
    import pandas as pd

    # 用 calamine 取得 sheet 名稱列表
    sheets = pd.ExcelFile(template_path, engine="calamine").sheet_names

    # 找「上傳模板」的 index
    upload_idx = None
    for i, name in enumerate(sheets):
        if "上傳" in name or "upload" in name.lower() or "模板" in name:
            # 用 calamine 讀看看第一行是不是 ps_category
            df = pd.read_excel(template_path, sheet_name=i, header=None, engine="calamine", nrows=1)
            if df.shape[1] > 0 and str(df.iloc[0, 0]).startswith("ps_"):
                upload_idx = i
                break

    if upload_idx is None:
        upload_idx = 1  # fallback: 通常是第 2 個 sheet

    # 解析 workbook.xml.rels 找到 sheet index 對應的 XML 檔名
    with zipfile.ZipFile(template_path) as z:
        wb_xml = z.read("xl/workbook.xml").decode("utf-8")
        rels_xml = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")

    # 取得所有 sheet 的 r:id
    sheet_rids = re.findall(r'r:id="(rId\d+)"', wb_xml)
    # 取得 rId -> Target 的映射
    rid_to_target = dict(re.findall(
        r'Id="(rId\d+)"\s+Target="([^"]+)".*?Type="[^"]*worksheet"',
        rels_xml,
    ))

    if upload_idx < len(sheet_rids):
        rid = sheet_rids[upload_idx]
        target = rid_to_target.get(rid, f"worksheets/sheet{upload_idx + 1}.xml")
    else:
        target = "worksheets/sheet2.xml"

    return f"xl/{target}"


def _write_to_template(template_path: Path, output_path: Path, data_rows: list, num_cols: int):
    """
    複製蝦皮模板，只在「上傳模板」sheet 的第 6 行開始寫入資料。
    保留原始模板的所有隱藏 sheet、metadata、驗證規則。
    """
    import pandas as pd

    # 1. 讀取模板的 header（前 5 行）和 sharedStrings
    df_template = pd.read_excel(
        template_path, sheet_name="上傳模板", header=None, engine="calamine"
    )
    header_rows = df_template.iloc[:5]

    # 2. 找出上傳模板對應的 sheet XML
    sheet_xml_path = _find_upload_sheet(template_path)
    logger.debug(f"上傳模板 sheet XML: {sheet_xml_path}")

    # 3. 讀取原始模板的 sharedStrings（字串池）
    with zipfile.ZipFile(template_path) as z:
        shared_strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss_xml = z.read("xl/sharedStrings.xml").decode("utf-8")
            # 解析現有 shared strings
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            root = ET.fromstring(ss_xml)
            for si in root.findall("s:si", ns):
                t = si.find("s:t", ns)
                shared_strings.append(t.text if t is not None and t.text else "")

    # 建立字串 -> index 的映射
    ss_map = {s: i for i, s in enumerate(shared_strings)}

    def get_ss_index(text: str) -> int:
        """取得或新增 sharedStrings index。"""
        if text in ss_map:
            return ss_map[text]
        idx = len(shared_strings)
        shared_strings.append(text)
        ss_map[text] = idx
        return idx

    # 4. 建立新的 sheet XML（保留 header + 加入資料行）
    all_rows = []

    # Header rows (前 5 行)
    for r_idx in range(5):
        cells = []
        for c_idx in range(num_cols):
            val = header_rows.iloc[r_idx, c_idx]
            if pd.isna(val):
                continue
            col_letter = _col_to_letter(c_idx)
            cell_ref = f"{col_letter}{r_idx + 1}"
            val_str = str(val)
            ss_idx = get_ss_index(val_str)
            cells.append(f'<c r="{cell_ref}" t="s"><v>{ss_idx}</v></c>')
        all_rows.append(f'<row r="{r_idx + 1}">{"".join(cells)}</row>')

    # Data rows (第 6 行開始)
    for d_idx, row_data in enumerate(data_rows):
        r_num = 6 + d_idx
        cells = []
        for c_idx in range(num_cols):
            val = row_data[c_idx] if c_idx < len(row_data) else None
            if val is None:
                continue
            col_letter = _col_to_letter(c_idx)
            cell_ref = f"{col_letter}{r_num}"

            if isinstance(val, (int, float)):
                cells.append(f'<c r="{cell_ref}"><v>{val}</v></c>')
            else:
                val_str = str(val)
                ss_idx = get_ss_index(val_str)
                cells.append(f'<c r="{cell_ref}" t="s"><v>{ss_idx}</v></c>')
        all_rows.append(f'<row r="{r_num}">{"".join(cells)}</row>')

    # 組裝 sheet XML
    last_row = 5 + len(data_rows)
    last_col = _col_to_letter(num_cols - 1)
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:{last_col}{last_row}"></dimension>'
        '<sheetViews><sheetView tabSelected="true" workbookViewId="0"></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"></sheetFormatPr>'
        f'<sheetData>{"".join(all_rows)}</sheetData>'
        '</worksheet>'
    )

    # 5. 重建 sharedStrings.xml
    ss_items = "".join(
        f'<si><t xml:space="preserve">{_xml_escape(s)}</t></si>'
        for s in shared_strings
    )
    ss_xml_new = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        f' count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f'{ss_items}</sst>'
    )

    # 6. 複製模板 zip，替換 sheet XML 和 sharedStrings
    with zipfile.ZipFile(template_path, "r") as z_in:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z_out:
            for item in z_in.infolist():
                if item.filename == sheet_xml_path:
                    z_out.writestr(item, sheet_xml.encode("utf-8"))
                elif item.filename == "xl/sharedStrings.xml":
                    z_out.writestr(item, ss_xml_new.encode("utf-8"))
                else:
                    z_out.writestr(item, z_in.read(item.filename))


def _col_to_letter(col_idx: int) -> str:
    """0-indexed column index → Excel column letter (A, B, ..., Z, AA, AB, ...)。"""
    result = ""
    idx = col_idx
    while True:
        result = chr(65 + idx % 26) + result
        idx = idx // 26 - 1
        if idx < 0:
            break
    return result


def _xml_escape(text: str) -> str:
    """XML 特殊字元轉義。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _build_product_rows(
    product_data: dict,
    ai_content: dict,
    image_paths: dict,
    user_config: dict,
    generated_images: list | None = None,
    num_cols: int = 43,
) -> list[list]:
    """
    為單一商品建立蝦皮 Excel 資料行。
    抽取自 generate_shopee_excel 的核心邏輯，供批次使用。
    """
    skus = product_data.get("skus", [])
    selected_sku_names = user_config.get("selected_skus", [])

    if selected_sku_names:
        selected_skus = [s for s in skus if any(
            sel in str(s.get("attributes", {}).values()) for sel in selected_sku_names
        )]
        if not selected_skus:
            selected_skus = skus[:len(selected_sku_names)]
    else:
        selected_skus = skus

    if not selected_skus:
        selected_skus = [{"attributes": {}, "price": 0, "stock": 0}]

    item_id = product_data.get("item_id", "unknown")
    title = ai_content.get("title", product_data.get("title", ""))
    description = ai_content.get("description", "")
    selling_price = user_config.get("selling_price", 99)
    stock = user_config.get("stock_per_option", 10)
    weight = user_config.get("weight", 0.1)
    category = user_config.get("category", "")

    # 蝦皮需要 https 圖片網址，優先用 1688 原圖 URL（去 webp 後綴轉 JPG）
    main_imgs = [_to_jpg_url(u) for u in (product_data.get("main_images", []) or image_paths.get("main", []))]
    sku_imgs = product_data.get("sku_images", {}) or image_paths.get("sku", {})

    # 合併圖片：Gemini 生成圖優先，然後 1688 原圖
    all_images = []
    if generated_images:
        all_images.extend(generated_images)
    all_images.extend(main_imgs)

    has_variations = len(selected_skus) > 1
    var_name = ""
    if has_variations and selected_skus[0].get("attributes"):
        var_name = list(selected_skus[0]["attributes"].keys())[0]
        var_name = var_name.replace("颜色", "顏色").replace("尺码", "尺碼").replace("规格", "規格")

    rows = []
    for i, sku in enumerate(selected_skus):
        row = [None] * num_cols

        # 每一行都要填的商品基本資訊
        row[COL["category"]] = category
        row[COL["product_name"]] = title
        row[COL["description"]] = description
        row[COL["min_purchase"]] = 1
        row[COL["parent_sku"]] = f"1688-{item_id}"
        row[COL["dangerous"]] = "否"
        row[COL["weight"]] = weight

        if i == 0:
            # 圖片只填第一行
            if all_images:
                row[COL["cover_image"]] = str(all_images[0])
                for j, img in enumerate(all_images[1:9]):
                    col_key = f"image_{j+1}"
                    if col_key in COL:
                        row[COL[col_key]] = str(img)

            for lc in LOGISTICS_COLS:
                row[lc] = "啟用"

        if has_variations:
            row[COL["var_id"]] = f"1688-{item_id}" if i == 0 else ""
            row[COL["var_name_1"]] = var_name if i == 0 else ""

            attr_values = list(sku.get("attributes", {}).values())
            option_name = attr_values[0] if attr_values else f"選項{i+1}"
            option_name = option_name.replace("颜色", "顏色")
            row[COL["var_option_1"]] = option_name

            sku_img = sku_imgs.get(attr_values[0], "") if attr_values else ""
            row[COL["var_image"]] = _to_jpg_url(sku_img) if sku_img else ""

        row[COL["price"]] = selling_price
        row[COL["stock"]] = stock
        row[COL["option_sku"]] = f"{item_id}-{i:03d}"

        rows.append(row)

    return rows


def generate_batch_shopee_excel(
    products: list[dict],
    output_path: Path,
    template_path: Path | None = None,
) -> Path:
    """
    批次生成蝦皮上傳 Excel（多商品合併為一個檔案）。

    Args:
        products: 每個商品的資料 dict，包含：
            - product_data: 1688 商品 JSON
            - ai_content: {"title", "description"}
            - image_paths: {"main": [...], "detail": [...], "sku": {...}}
            - generated_images: [Path, ...] Gemini 生成的圖片
            - user_config: {"category", "selling_price", "stock_per_option", "weight"}
        output_path: 輸出的 Excel 路徑
        template_path: 蝦皮模板路徑

    Returns:
        輸出的 Excel 路徑
    """
    import pandas as pd

    template = template_path or TEMPLATE_PATH
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")

    df_template = pd.read_excel(template, sheet_name="上傳模板", header=None, engine="calamine")
    header_rows = df_template.iloc[:5].copy()
    num_cols = df_template.shape[1]

    all_rows = []
    for product in products:
        product_rows = _build_product_rows(
            product_data=product["product_data"],
            ai_content=product["ai_content"],
            image_paths=product["image_paths"],
            user_config=product["user_config"],
            generated_images=product.get("generated_images", []),
            num_cols=num_cols,
        )
        all_rows.extend(product_rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_to_template(template, output_path, all_rows, num_cols)

    total_skus = len(all_rows)
    logger.info(f"蝦皮批次 Excel 已產生: {output_path} ({len(products)} 商品, {total_skus} SKU rows)")
    return output_path
