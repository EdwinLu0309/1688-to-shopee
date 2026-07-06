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
import asyncio
import json
from pathlib import Path

from loguru import logger

from config.settings import OUTPUT_DIR
from scraper.color_policy import base_color, select_first_axis
from scraper.copywriter import build_variants, generate_listing
from scraper.downloader import download_product_images_from_json
from scraper.shopee_excel import TEMPLATE_PATH, generate_batch_two_tier_excel
from scraper.video_maker import collect_images, make_product_video


def base_color_of(color_map: dict, key: str) -> str:
    """第一軸 key → 純底色（去身高款/版型）。用「簡體原始 key」為準（穩定），
    與 select_first_axis 的分組一致；Claude 繁體渲染多變不可靠。"""
    return base_color(key) or key


def _gpt_images_for(product_data: dict, code: str, category: str,
                    item_dir: Path, product_name: str) -> list[str]:
    """✨ GPT 路線：下載 1688 圖當參考 → 生品牌電商圖 → 上傳圖床 → 回公開 URL 清單。

    圖床未設定 / 無參考圖 / 生圖失敗 → 回 []（呼叫端會退回 1688 原圖）。
    """
    from scraper.gpt_image_generator import generate_all
    from scraper.image_host import is_configured, upload_images

    if not is_configured():
        logger.warning(f"[{code}] 圖床未設定（SUPABASE_*），GPT 路線退回 1688 圖")
        return []
    main_dir = item_dir / "images" / "main"
    if not (main_dir.exists() and any(main_dir.glob("*.*"))):
        logger.info(f"[{code}] 下載 1688 主圖當 GPT 參考…")
        asyncio.run(download_product_images_from_json(product_data, item_dir / "images"))
    refs = sorted(main_dir.glob("*.*")) if main_dir.exists() else []
    if not refs:
        logger.warning(f"[{code}] 無主圖可當參考，GPT 路線退回 1688 圖")
        return []
    logger.info(f"[{code}] ✨ GPT 生圖中（{len(refs)} 張參考）…")
    gen = generate_all(refs, item_dir / "images" / "generated", product_name, category)
    if not gen:
        logger.warning(f"[{code}] GPT 沒生出圖，退回 1688 圖")
        return []
    urls = upload_images(gen, code, subdir="gpt")
    logger.info(f"[{code}] ✨ GPT 完成：{len(gen)} 張生圖 → {len(urls)} 張上圖床")
    return urls


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
            "style_note": entry.get("style_filter", ""),  # 第一層：Edwin 的款式備註
        })
        if ai_content.get("error"):
            logger.error(f"[{code}] 文案生成失敗：{ai_content.get('error')}")
            return None
        ai_cache.write_text(json.dumps(ai_content, ensure_ascii=False, indent=2), encoding="utf-8")

    short_name = ai_content.get("product_short_name", "")
    size_labels = ai_content.get("size_labels", {})
    color_map = ai_content.get("color_map", {})

    # ── 尺寸：全留（尺寸不對無法替換，是硬需求）──
    # 用 Claude 的 size_labels keys（已正規化 S/M/L、值已換算公斤/繁體），而非 1688 原始。
    all_sizes = list(size_labels.keys()) or product_data.get("sizes", [])
    sizes_spec = entry.get("sizes")
    if not sizes_spec or str(sizes_spec).strip().lower() == "all":
        selected_sizes = all_sizes
    else:
        selected_sizes = [s.strip() for s in str(sizes_spec).split(",") if s.strip()]
    n_sizes = max(1, len(selected_sizes))

    # ── 顏色：明確 colors 覆寫 > 兩層篩選（款式備註 → 中性色 ≤5）──
    color_flag = None
    if entry.get("colors"):
        # 手動指定顏色（如舊 P-a1 --colors）→ 照填，不套中性政策
        selected_colors, color_map = _parse_colors(entry["colors"], color_map)
    else:
        # 第一層：Claude 依款式備註留下的第一軸選項（沒有就全部）
        all_keys = list(color_map.keys())
        kept = ai_content.get("style_kept") or []
        kept = [k for k in kept if k in color_map] or all_keys  # 對不上就退回全部
        # 第二層：第一軸＝顏色×身高款；身高款當尺寸全留，只砍底色到中性 ≤5，100 保底。
        pick = select_first_axis(kept, color_map, n_sizes, max_base_colors=5, sku_cap=100)
        selected_colors = pick["selected"]
        color_flag = pick["flag"]
        if pick["dropped_fashion"]:
            logger.info(f"[{code}] 丟亮色系（不進貨）：{sorted({base_color_of(color_map, k) for k in pick['dropped_fashion']})}")
        if pick["dropped_overflow"]:
            logger.info(f"[{code}] 熱門底色超額砍：{sorted({base_color_of(color_map, k) for k in pick['dropped_overflow']})}")
        if color_flag:
            logger.warning(f"[{code}] {color_flag}")
            if not selected_colors:  # 0 中性色 → 保底留原始前幾個（仍標記人工覆核）
                selected_colors = kept[:5]

    variants = build_variants(code, short_name, color_map,
                              selected_colors, size_labels, selected_sizes)

    sku_count = variants.get("sku_count", 0)
    n_base = len({base_color_of(color_map, k) for k in selected_colors})
    logger.info(f"[{code}] 留 {n_base} 底色（{len(selected_colors)} 個第一軸選項含身高款）"
                f" × {n_sizes} 尺碼 = {sku_count} SKU"
                f"（{'✓' if sku_count <= 100 else '⚠ 超過 100！'}）"
                f" 底色：{sorted({base_color_of(color_map, k) for k in selected_colors})}")

    # 路線：gpt = 生品牌電商圖上圖床當商品圖；1688（預設）= 直接用 1688 原圖
    image_urls = []
    if str(entry.get("route", "1688")).lower() == "gpt":
        image_urls = _gpt_images_for(
            product_data, code, str(entry.get("category", "")), item_dir,
            ai_content.get("product_short_name") or product_data.get("title", ""))

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
            "size_chart_url": entry.get("size_chart_url", ""),  # Q 欄圖片尺寸表
            "image_skip": entry.get("image_skip", []),          # 排除的主圖 index（如有簡體字）
            "pre_order_days": entry.get("pre_order_days"),       # AP 較長備貨天數
            "image_urls": image_urls,                            # ✨ GPT 生圖圖床 URL（有=覆蓋 1688）
        },
        "_meta": {"code": code, "item_id": item_id,
                  "sku_count": sku_count,
                  "n_base_colors": n_base, "n_options": len(selected_colors),
                  "n_sizes": n_sizes, "color_flag": color_flag,
                  "route": entry.get("route", "1688"), "gpt_images": len(image_urls),
                  "title": ai_content.get("title", "")},
    }


def _make_video_for(product: dict, video_n: int = 9) -> str | None:
    """為單一商品合成短影片：缺本機圖就先下載，再挑 n 張合成 → video/{編號}.mp4。

    影片吃本機圖（Excel 用的是 1688 URL、不落地），故這裡確保圖先下好。
    回傳影片路徑字串；無圖或 ffmpeg 缺失回 None。
    """
    meta = product["_meta"]
    item_id, code = meta["item_id"], meta["code"]
    item_dir = Path(OUTPUT_DIR) / item_id
    try:
        if not collect_images(item_dir):
            logger.info(f"[{code}] 本機無圖，下載 1688 圖片供影片使用…")
            asyncio.run(download_product_images_from_json(product["product_data"], item_dir / "images"))
        # ✨ GPT 路線：影片用生的品牌電商圖（generated/gpt_*.png）
        gen_dir = item_dir / "images" / "generated"
        gpt_imgs = sorted(gen_dir.glob("gpt_*.png")) if gen_dir.exists() else []
        curated = None
        if product.get("config", {}).get("image_urls") and gpt_imgs:
            curated = gpt_imgs[:video_n]
        # 1688 路線：排除有簡體字的主圖（config image_skip）：挑乾淨主圖(+SKU)前 n 張
        skip = set(product.get("config", {}).get("image_skip", []))
        if curated is None and skip:
            main_dir = item_dir / "images" / "main"
            mains = sorted(main_dir.glob("*.*")) if main_dir.exists() else []
            clean_mains = [p for i, p in enumerate(mains) if i not in skip]
            sku_dir = item_dir / "images" / "sku"
            skus = sorted(sku_dir.glob("*.*")) if sku_dir.exists() else []
            curated = (clean_mains + skus)[:video_n]
        out = make_product_video(item_dir, n=video_n, name=code, images=curated)
        if out is None:
            logger.warning(f"[{code}] 無可用圖片，跳過影片")
            return None
        logger.info(f"[{code}] 影片：{out}")
        return str(out)
    except FileNotFoundError as e:
        logger.warning(f"[{code}] ffmpeg 缺失，跳過影片：{e}")
        return None
    except Exception as e:
        logger.error(f"[{code}] 影片合成失敗：{e}")
        return None


def assemble_upload_assets(code: str, item_id: str) -> Path | None:
    """把「要手動補到蝦皮」的素材（影片 + 尺寸表）按編號歸到一個好找的資料夾。

    產出 output/上架素材/{編號}/：
      {編號}_影片.mp4     ← 蝦皮商品影片（大量上架 Excel 沒影片欄，手動補）
      {編號}_尺寸表.png   ← 繁體尺寸表（若有；上傳蝦皮後可取得網址填 Q 欄）

    直觀用法：上架某商品時，打開 output/上架素材/{編號}/ 把裡面的東西補上蝦皮即可。
    """
    import shutil

    item_dir = Path(OUTPUT_DIR) / item_id
    dest = Path(OUTPUT_DIR) / "上架素材" / code
    dest.mkdir(parents=True, exist_ok=True)

    copied = []
    video = item_dir / "video" / f"{code}.mp4"
    if video.exists():
        shutil.copy2(video, dest / f"{code}_影片.mp4")
        copied.append("影片")
    size_chart = item_dir / "images" / "generated" / f"size_chart_{code}.png"
    if size_chart.exists():
        shutil.copy2(size_chart, dest / f"{code}_尺寸表.png")
        copied.append("尺寸表")

    if copied:
        logger.info(f"[{code}] 上架素材已歸位 {dest}（{'/'.join(copied)}）")
        return dest
    return None


def run_batch_two_tier(
    manifest_path: Path | None = None,
    json_dir: Path = Path("output"),
    output_path: Path | None = None,
    template_path: Path | None = None,
    make_video: bool = True,
    video_n: int = 9,
    products: list[dict] | None = None,
) -> dict:
    """逐商品處理（文案+變體，選配影片）→ 合併蝦皮二階 Excel。

    輸入二擇一：manifest_path（JSON 檔）或 products（清單，如 ai_list_reader 的輸出）。
    """
    if products is not None:
        entries = products
        tpl = template_path or TEMPLATE_PATH
    else:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        entries = manifest.get("products", [])
        tpl = template_path or (
            Path(manifest["template"]) if manifest.get("template") else TEMPLATE_PATH
        )
    if not entries:
        logger.warning("沒有商品可處理")
        return {"total": 0, "success": 0, "failed": 0, "excel_path": None, "failures": []}

    prepared, failures = [], []
    for entry in entries:
        code = entry.get("code", entry.get("item_id"))
        logger.info(f"{'='*50}\n處理 {code} (item_id: {entry.get('item_id')})")
        try:
            p = _prepare_product(entry, json_dir)
            if p is None:
                failures.append({"code": code, "error": "缺 JSON 或文案失敗"})
            else:
                if make_video:
                    p["_meta"]["video"] = _make_video_for(p, video_n)
                # 影片 + 尺寸表歸到 output/上架素材/{編號}/ 方便手動補上蝦皮
                assemble_upload_assets(p["_meta"]["code"], p["_meta"]["item_id"])
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
        vtag = " | 🎬" if m.get("video") else ""
        logger.info(f"  ✓ {m['code']}: {m['sku_count']} SKU{vtag} | {m['title'][:40]}")
    if failures:
        for f in failures:
            logger.warning(f"  ✗ {f['code']}: {f['error']}")
    return summary
