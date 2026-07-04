"""
批次 Pipeline v2（過審二階路徑）：
manifest 清單 → 逐商品（Claude 文案 + 程式拼變體）→ 合併成一個蝦皮二階上架 Excel。

與舊 batch_pipeline.py 的差異：
- 舊版走 Gemini 單階（generate_shopee_content + generate_batch_shopee_excel），已停用。
- 本版走 copywriter.generate_listing + build_variants + generate_batch_two_tier_excel
  （= #S064 實測過審的路徑），每商品一個遞增規格識別碼。

為什麼用 manifest 而非直接解析採購表：
採購表（Google Sheet）本身沒有「編號」、沒有「蝦皮分類 ID」，1688 網址又是超連結
（gviz CSV 讀不到 target）。編號 / 分類 ID / 挑色都是人為決策。manifest 把這些決策
明確落地成一份可版本控管的輸入，採購表僅作輔助（帶售價/品名，選用）。

manifest 格式（JSON）：
{
  "template": "config/shopee_template.xlsx",   // 選填，預設用內建模板
  "products": [
    {
      "item_id": "784712770291",   // 對應 json_dir/{item_id}.json（extract_1688.js 抓的）
      "code": "P-a1",              // 內部編號 → 變體命名 + 主商品貨號
      "price": 998,                // 蝦皮售價 (NT$)
      "stock": 10,                 // 每 SKU 庫存
      "category": "100358",        // 蝦皮分類 ID（數字字串）
      "colors": "米白色【长裤】=米白色,黑色【长裤】=黑色,灰色【长裤】=灰色",
                                   // 挑第一軸：逗號分隔，可 src=乾淨名；省略/"all"=全部用 color_map
      "sizes": "",                 // 挑尺碼：逗號分隔；省略/"all"=全部
      "reuse_content": true,       // 用 output/{item_id}/ai_content.json 快取，不重呼 Claude
      "demand": "",                // 訂貨脈絡（給文案參考）
      "weight": 0.1
    }
  ]
}
"""
import json
from pathlib import Path

from loguru import logger

from config.settings import OUTPUT_DIR
from scraper.copywriter import build_variants, generate_listing
from scraper.shopee_excel import TEMPLATE_PATH, generate_batch_two_tier_excel


def _parse_colors(colors_spec: str | None, color_map: dict) -> tuple[list[str], dict]:
    """解析 colors 設定 → (selected_colors 的 src key 清單, 更新後的 color_map)。

    colors_spec 支援 "src=乾淨名" 覆寫 color_map；省略或 "all" = 全部用 color_map。
    """
    color_map = dict(color_map)
    if not colors_spec or colors_spec.strip().lower() == "all":
        return list(color_map.keys()), color_map
    selected = []
    for part in colors_spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            src, clean = part.split("=", 1)
            src, clean = src.strip(), clean.strip()
            color_map[src] = clean
        else:
            src = part
        selected.append(src)
    return selected, color_map


def _prepare_product(entry: dict, json_dir: Path) -> dict | None:
    """把一個 manifest 商品項處理成 generate_batch_two_tier_excel 需要的 dict。"""
    item_id = str(entry["item_id"])
    code = entry.get("code", item_id)

    # 找 pre-scraped JSON
    candidates = [json_dir / f"{item_id}.json", json_dir / item_id / f"{item_id}.json"]
    product_json = next((p for p in candidates if p.exists()), None)
    if product_json is None:
        logger.warning(f"[{code}] 找不到 {item_id}.json（{[str(c) for c in candidates]}），跳過")
        return None
    product_data = json.loads(product_json.read_text(encoding="utf-8"))

    # 文案：快取優先
    item_dir = Path(OUTPUT_DIR) / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    ai_cache = item_dir / "ai_content.json"
    if entry.get("reuse_content") and ai_cache.exists():
        ai_content = json.loads(ai_cache.read_text(encoding="utf-8"))
        logger.info(f"[{code}] 使用快取文案")
    else:
        ai_content = generate_listing(product_data, {
            "code": code,
            "selling_price": entry.get("price", ""),
            "demand": entry.get("demand", ""),
            "category": entry.get("category", ""),
        })
        if ai_content.get("error"):
            logger.error(f"[{code}] 文案生成失敗：{ai_content.get('error')}")
            return None
        ai_cache.write_text(json.dumps(ai_content, ensure_ascii=False, indent=2), encoding="utf-8")

    short_name = ai_content.get("product_short_name", "")
    size_labels = ai_content.get("size_labels", {})
    selected_colors, color_map = _parse_colors(entry.get("colors"), ai_content.get("color_map", {}))

    all_sizes = product_data.get("sizes", []) or list(size_labels.keys())
    sizes_spec = entry.get("sizes")
    if not sizes_spec or str(sizes_spec).strip().lower() == "all":
        selected_sizes = all_sizes
    else:
        selected_sizes = [s.strip() for s in str(sizes_spec).split(",") if s.strip()]

    variants = build_variants(code, short_name, color_map,
                              selected_colors, size_labels, selected_sizes)

    return {
        "product_data": product_data,
        "ai_content": ai_content,
        "variants": variants,
        "config": {
            "category": str(entry.get("category", "")),
            "selling_price": entry.get("price", 99),
            "stock_per_option": entry.get("stock", 10),
            "weight": entry.get("weight", 0.1),
            "code": code,
        },
        "_meta": {"code": code, "item_id": item_id,
                  "sku_count": variants.get("sku_count", 0),
                  "title": ai_content.get("title", "")},
    }


def run_batch_two_tier(
    manifest_path: Path,
    json_dir: Path,
    output_path: Path | None = None,
    template_path: Path | None = None,
) -> dict:
    """讀 manifest → 逐商品處理 → 合併蝦皮二階 Excel。"""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    entries = manifest.get("products", [])
    if not entries:
        logger.warning("manifest 中沒有 products")
        return {"total": 0, "success": 0, "failed": 0, "excel_path": None, "failures": []}

    tpl = template_path or (
        Path(manifest["template"]) if manifest.get("template") else TEMPLATE_PATH
    )

    prepared, failures = [], []
    for entry in entries:
        code = entry.get("code", entry.get("item_id"))
        logger.info(f"{'='*50}\n處理 {code} (item_id: {entry.get('item_id')})")
        try:
            p = _prepare_product(entry, json_dir)
            if p is None:
                failures.append({"code": code, "error": "缺 JSON 或文案失敗"})
            else:
                prepared.append(p)
        except Exception as e:
            logger.error(f"[{code}] 例外：{e}")
            failures.append({"code": code, "error": str(e)})

    if not prepared:
        logger.warning("沒有成功處理的商品，不產生 Excel")
        return {"total": len(entries), "success": 0, "failed": len(failures),
                "excel_path": None, "failures": failures}

    if output_path is None:
        output_path = Path(OUTPUT_DIR) / "shopee_batch_upload.xlsx"
    generate_batch_two_tier_excel(prepared, Path(output_path), tpl)

    summary = {
        "total": len(entries),
        "success": len(prepared),
        "failed": len(failures),
        "excel_path": Path(output_path),
        "failures": failures,
        "products": [p["_meta"] for p in prepared],
    }
    logger.info(f"{'='*50}\n批次完成：{summary['success']}/{summary['total']} 成功"
                f"，Excel：{output_path}")
    for m in summary["products"]:
        logger.info(f"  ✓ {m['code']}: {m['sku_count']} SKU | {m['title'][:40]}")
    if failures:
        for f in failures:
            logger.warning(f"  ✗ {f['code']}: {f['error']}")
    return summary
