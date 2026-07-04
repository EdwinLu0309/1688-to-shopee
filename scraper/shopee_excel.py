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


# 內部 key（模板第 0 列）→ 語意名稱。用 key 動態對應欄位，避免不同版本模板
# 欄數/欄序不同造成跑版（曾踩過：43 欄 vs 44 欄、物流頻道數不同）。
_KEY_TO_NAME = {
    "ps_category": "category",
    "ps_product_name": "product_name",
    "ps_product_description": "description",
    "ps_minimum_purchase_quantity": "min_purchase",
    "ps_sku_parent_short": "parent_sku",
    "ps_dangerous_goods": "dangerous",
    "et_title_variation_integration_no": "var_id",
    "et_title_variation_1": "var_name_1",
    "et_title_option_for_variation_1": "var_option_1",
    "et_title_image_per_variation": "var_image",
    "et_title_variation_2": "var_name_2",
    "et_title_option_for_variation_2": "var_option_2",
    "ps_price": "price",
    "ps_stock": "stock",
    "ps_sku_short": "option_sku",
    "ps_item_cover_image": "cover_image",
    "ps_weight": "weight",
    "ps_product_pre_order_dts": "pre_order_days",
}


def build_col_map(df_template) -> tuple[dict, dict]:
    """從模板第 0 列的內部 key 動態建立 {語意名稱: 欄index} + {物流頻道id: 欄index}。"""
    col: dict = {}
    logistics: dict = {}
    for c in range(df_template.shape[1]):
        key = str(df_template.iloc[0, c]).split("|")[0].strip()
        if key in _KEY_TO_NAME:
            col[_KEY_TO_NAME[key]] = c
        elif key.startswith("ps_item_image_"):
            col[f"image_{key.rsplit('_', 1)[1]}"] = c
        elif key.startswith("channel_id."):
            logistics[key.split(".", 1)[1]] = c   # "30001" -> col index
    return col, logistics


# JoysLu Lady 預設啟用的物流頻道（依 Edwin 賣場設定；預購品不支援「蝦皮店到店-隔日到貨」）
DEFAULT_ENABLED_CHANNELS = {
    "30020",  # 新竹物流
    "30006",  # 全家
    "30005",  # 7-ELEVEN
    "30017",  # 店到家宅配
    "30015",  # 蝦皮店到店
    "30018",  # 嘉里快遞
}


def build_two_tier_rows(
    product_data: dict,
    ai_content: dict,
    variants: dict,
    config: dict,
    col: dict,
    logistics: dict,
    num_cols: int,
    var_group_id: int = 1,
) -> list[list]:
    """建立蝦皮「二階規格」(顏色 × 尺碼) 的資料行。

    col / logistics：build_col_map() 動態解出的欄位對應（不寫死 index）。
    variants：scraper.copywriter.build_variants() 的輸出。
    config：{"category","selling_price","stock_per_option","weight","code",
            "enabled_channels"(set), "pre_order_days"(int or None)}

    重要（依 CLAUDE.md 蝦皮注意事項）：
    - 禁運品 = No / 物流啟用 = 開啟、停用 = 關閉
    - 每個 SKU 行都要填商品名稱 + 規格識別碼 + 規格名稱1/2
    - 圖片用 https 網址只填第一行
    """
    COL = col  # 區域別名，下面沿用
    enabled = config.get("enabled_channels") or DEFAULT_ENABLED_CHANNELS
    pre_order_days = config.get("pre_order_days")
    title = ai_content.get("title", product_data.get("title", ""))
    description = ai_content.get("description", "")
    code = config.get("code") or product_data.get("item_id", "unknown")
    price = config.get("selling_price", 99)
    stock = config.get("stock_per_option", 10)
    weight = config.get("weight", 0.1)
    category = config.get("category", "")

    main_imgs = [_to_jpg_url(u) for u in product_data.get("main_images", [])]
    sku_imgs = product_data.get("sku_images", {})

    colors = variants.get("規格1_顏色", [])
    sizes = variants.get("規格2_尺碼", [])
    if not sizes:  # 沒有第二軸 → 退化成單軸
        sizes = [{"size": "", "option_name": ""}]

    rows = []
    first = True
    for ci, c in enumerate(colors):
        color_opt = c["option_name"]                       # 編號_簡稱_顏色
        color_img = _to_jpg_url(sku_imgs.get(c["src_1688"], "")) if sku_imgs.get(c["src_1688"]) else ""
        color_first = True
        for s in sizes:
            row = [None] * num_cols
            # 以下全部對齊「已驗證能過的檔」(花花 2026-05-22)：
            # - 數字欄寫文字整數字串（蝦皮 Go ParseUint，寫數字會讀成 "1.0" 失敗）
            # - 主商品貨號 / 危險物品：留空（變體商品填了會「型號與變體不匹配」）
            # - 商品選項貨號（型號）：純英數、每個顏色一個（不可含中文）
            row[COL["category"]] = category
            row[COL["product_name"]] = title
            row[COL["description"]] = description
            row[COL["min_purchase"]] = "1"
            # 測試：主商品貨號加回編號（商品識別用）。若觸發「型號與變體不匹配」要改回留空。
            row[COL["parent_sku"]] = code
            row[COL["weight"]] = str(weight)
            row[COL["price"]] = str(int(round(float(price))))
            row[COL["stock"]] = str(int(round(float(stock))))
            # 規格欄位：每行都填；識別碼相同 → 歸成同一商品
            row[COL["var_id"]] = str(int(var_group_id))
            row[COL["var_name_1"]] = "顏色"
            row[COL["var_option_1"]] = color_opt
            if s["option_name"]:
                row[COL["var_name_2"]] = "尺碼"
                row[COL["var_option_2"]] = s["option_name"]
            # 商品選項貨號（型號）：純英數、每個 SKU 唯一（色序+尺碼，庫存好追蹤）
            row[COL["option_sku"]] = f"{code}-{ci + 1}-{s['size']}".rstrip("-")

            # ── 以下「每一行都填」（Edwin 要求：規格圖同色同一張、商品圖/物流每行都一樣，不要跳填）──
            # 規格圖片：同一顏色用同一張
            if color_img:
                row[COL["var_image"]] = color_img
            # 商品圖片（主圖 + 1~8）：每行都放同一組
            if main_imgs:
                row[COL["cover_image"]] = main_imgs[0]
                for j, img in enumerate(main_imgs[1:9]):
                    ck = f"image_{j+1}"
                    if ck in COL:
                        row[COL[ck]] = img
            # 物流：啟用填「開啟」，停用的「留空」（同能過的檔；填「關閉」非必要）
            for cid, lc in logistics.items():
                if cid in enabled:
                    row[lc] = "開啟"
            # 較長備貨天數（預購）
            if pre_order_days and "pre_order_days" in COL:
                row[COL["pre_order_days"]] = str(int(pre_order_days))

            rows.append(row)
            first = False
            color_first = False
    return rows


def generate_two_tier_excel(
    product_data: dict,
    ai_content: dict,
    variants: dict,
    config: dict,
    output_path: Path,
    template_path: Path | None = None,
) -> Path:
    """單一商品 → 二階規格蝦皮上架 Excel。"""
    import pandas as pd

    template = template_path or TEMPLATE_PATH
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    df_template = pd.read_excel(template, sheet_name="上傳模板", header=None, engine="calamine")
    num_cols = df_template.shape[1]
    col, logistics_cols = build_col_map(df_template)
    rows = build_two_tier_rows(product_data, ai_content, variants, config,
                               col, logistics_cols, num_cols)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _insert_data_rows(template, output_path, rows, num_cols)
    logger.info(f"蝦皮 Excel（二階）已產生：{output_path}（{len(rows)} SKU 行）")
    return output_path


def generate_batch_two_tier_excel(
    products: list[dict],
    output_path: Path,
    template_path: Path | None = None,
) -> Path:
    """多商品 → 合併成一個蝦皮二階上架 Excel（每商品一個規格識別碼）。

    Args:
        products: 每筆 {"product_data","ai_content","variants","config"}，
                  格式同 generate_two_tier_excel 的參數。
        output_path: 輸出 Excel 路徑
        template_path: 蝦皮模板

    重點：每個商品用「遞增的規格識別碼」(var_group_id = 1,2,3…)，這是蝦皮把
    多列歸成「同一個商品」的鑰匙；不同商品必須不同 id，否則會被併成一個商品。
    """
    import pandas as pd

    template = template_path or TEMPLATE_PATH
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    df_template = pd.read_excel(template, sheet_name="上傳模板", header=None, engine="calamine")
    num_cols = df_template.shape[1]
    col, logistics_cols = build_col_map(df_template)

    all_rows: list[list] = []
    for gid, p in enumerate(products, start=1):
        rows = build_two_tier_rows(
            p["product_data"], p["ai_content"], p["variants"], p["config"],
            col, logistics_cols, num_cols, var_group_id=gid,
        )
        all_rows.extend(rows)
        logger.info(f"  [商品 {gid}] {p['config'].get('code','')} → {len(rows)} SKU 行")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _insert_data_rows(template, output_path, all_rows, num_cols)
    logger.info(f"蝦皮批次 Excel（二階）已產生：{output_path}"
                f"（{len(products)} 商品，{len(all_rows)} SKU 行）")
    return output_path


# 蝦皮從第 7 列開始讀資料（前 6 列是表頭，第 6 列是提示行、保留不動）。
# 依「已驗證能過的檔」(花花 2026-05-22)：資料在第 7 列、6 列表頭全保留。
# 注意：第 2 列藏版本 hash → 全部表頭與其他 sheet 一律原封不動。
_HEADER_ROWS = 6


def _insert_data_rows(template_path: Path, output_path: Path, data_rows: list, num_cols: int) -> None:
    """把資料列插進模板，其餘 100% 原封不動。

    踩坑記錄：
    - 資料從第 7 列開始（保留全部 6 列表頭，含第 6 列提示行）。對齊能過的檔。
    - cell 用 sharedStrings（t="s"），不要用 inlineStr（蝦皮解析器只吃 sharedStrings）。
    - sharedStrings 只「追加」新字串、不動既有內容/索引 → 版本 hash 與其他 sheet 不受影響。
    """
    sheet_xml_path = _find_upload_sheet(template_path)
    with zipfile.ZipFile(template_path) as z:
        sheet_xml = z.read(sheet_xml_path).decode("utf-8")
        ss_xml = z.read("xl/sharedStrings.xml").decode("utf-8")

    # 既有 sharedStrings 數量（新字串從這個 index 之後接續，不碰既有）
    mu = re.search(r'<sst\b[^>]*\buniqueCount="(\d+)"', ss_xml)
    base = int(mu.group(1)) if mu else ss_xml.count("<si>")
    mc = re.search(r'<sst\b[^>]*\bcount="(\d+)"', ss_xml)
    base_count = int(mc.group(1)) if mc else base

    new_strings: list[str] = []
    idx_map: dict[str, int] = {}
    total_refs = 0

    def sidx(text: str) -> int:
        nonlocal total_refs
        total_refs += 1
        if text in idx_map:
            return idx_map[text]
        i = base + len(new_strings)
        new_strings.append(text)
        idx_map[text] = i
        return i

    rows_xml = []
    for d_idx, row_data in enumerate(data_rows):
        r_num = _HEADER_ROWS + 1 + d_idx  # 7, 8, ...
        cells = []
        for c_idx in range(num_cols):
            val = row_data[c_idx] if c_idx < len(row_data) else None
            if val is None or val == "":
                continue
            ref = f"{_col_to_letter(c_idx)}{r_num}"
            cells.append(f'<c r="{ref}" t="s"><v>{sidx(str(val))}</v></c>')
        rows_xml.append(f'<row r="{r_num}">{"".join(cells)}</row>')

    sheet_xml = sheet_xml.replace("</sheetData>", "".join(rows_xml) + "</sheetData>", 1)
    last_row = _HEADER_ROWS + len(data_rows)
    last_col = _col_to_letter(num_cols - 1)
    sheet_xml = re.sub(r'<dimension ref="[^"]*"',
                       f'<dimension ref="A1:{last_col}{last_row}"', sheet_xml, count=1)

    # 追加新字串到 sharedStrings（既有內容一字不動）+ 更新 count/uniqueCount
    new_si = "".join(f'<si><t xml:space="preserve">{_xml_escape(s)}</t></si>' for s in new_strings)
    ss_xml = ss_xml.replace("</sst>", new_si + "</sst>", 1)
    ss_xml = re.sub(r'(<sst\b[^>]*\buniqueCount=")\d+(")',
                    lambda m: m.group(1) + str(base + len(new_strings)) + m.group(2), ss_xml, count=1)
    ss_xml = re.sub(r'(<sst\b[^>]*\bcount=")\d+(")',
                    lambda m: m.group(1) + str(base_count + total_refs) + m.group(2), ss_xml, count=1)

    with zipfile.ZipFile(template_path, "r") as z_in:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z_out:
            for item in z_in.infolist():
                if item.filename == sheet_xml_path:
                    z_out.writestr(item, sheet_xml.encode("utf-8"))
                elif item.filename == "xl/sharedStrings.xml":
                    z_out.writestr(item, ss_xml.encode("utf-8"))
                else:
                    z_out.writestr(item, z_in.read(item.filename))


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
