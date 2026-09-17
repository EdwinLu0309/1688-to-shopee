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
import re
import json
from datetime import datetime
from pathlib import Path

from collections import Counter

from loguru import logger

from scraper.weight_parse import dims_cm, weight_kg

from config.settings import BATCH_DIR, OUTPUT_DIR, RAW_DIR
from scraper.color_policy import base_color, select_first_axis
from scraper.copywriter import build_variants, generate_listing
from scraper.downloader import download_product_images_from_json
from scraper.shopee_excel import generate_batch_two_tier_excel
from scraper.video_maker import collect_images, make_product_video


def base_color_of(color_map: dict, key: str) -> str:
    """第一軸 key → 純底色（去身高款/版型）。用「簡體原始 key」為準（穩定），
    與 select_first_axis 的分組一致；Claude 繁體渲染多變不可靠。"""
    return base_color(key) or key



# 1688 原始屬性名 → 蝦皮規格名稱。一軸商品的那一軸不一定是顏色。
_AXIS_ZH = {"颜色": "顏色", "顏色": "顏色", "规格": "規格", "規格": "規格",
            "尺码": "尺碼", "尺碼": "尺碼", "型号": "型號", "款式": "款式", "容量": "容量"}


def _axis1_name_for(product_data: dict, sp) -> str:
    """第一軸的蝦皮規格名稱。取 1688 SKU 的第一個屬性名；認不得就用賣場預設。"""
    for s in (product_data.get("skus") or []):
        for k in (s.get("attributes") or {}):
            name = _AXIS_ZH.get(str(k).strip())
            if name:
                if name != sp.axis1_name:
                    logger.info(f"第一軸依 1688 原始屬性名定為「{name}」"
                                f"（賣場預設是「{sp.axis1_name}」）")
                return name
            break
    return sp.axis1_name

def _gpt_images_for(product_data: dict, code: str, category: str,
                    item_dir: Path, product_name: str,
                    shop: str = "lady", img_template: str | None = None) -> list[str]:
    """✨ GPT 路線：下載 1688 圖當參考 → 生品牌電商圖 → 上傳圖床 → 回公開 URL 清單。

    圖床未設定 / 無參考圖 / 生圖失敗 → 回 []（呼叫端會退回 1688 原圖）。
    """
    from scraper.gpt_image_generator import generate_cover
    from scraper.image_host import is_configured, upload_images

    if not is_configured():
        logger.warning(f"[{code}] 圖床未設定（SUPABASE_*），GPT 路線退回 1688 圖")
        return []
    main_dir = item_dir / "images" / "main"
    detail_dir = item_dir / "images" / "detail"
    if not (main_dir.exists() and any(main_dir.glob("*.*"))):
        logger.info(f"[{code}] 下載 1688 圖當 GPT 參考…")
        asyncio.run(download_product_images_from_json(product_data, item_dir / "images"))
    # 依 JoysLu AI Design Engine：主圖＝商品圖（以此為準）、細節圖＝1688 參考（不照抄）
    main_imgs = sorted(main_dir.glob("*.*"))[:8] if main_dir.exists() else []
    detail_imgs = sorted(detail_dir.glob("*.*"))[:6] if detail_dir.exists() else []
    if not (main_imgs or detail_imgs):
        logger.warning(f"[{code}] 無圖可當參考，GPT 路線退回 1688 圖")
        return []
    from scraper.gpt_image_generator import use_template
    logger.info(f"[{code}] ✨ GPT 生封面（規範：{shop}/{img_template or '全部'}）…")
    try:
        with use_template(shop, img_template):
            cover = generate_cover(main_imgs, detail_imgs,
                                   item_dir / "images" / "generated" / "cover.png")
    except FileNotFoundError as e:
        # 該賣場沒有圖片規範 → 退回 1688 原圖。**不要拿別家的規範硬生**（那會生出風格完全
        # 不對的圖，而且看起來像「功能有在跑」，比直接不生更難發現。）
        logger.warning(f"[{code}] {e} → 退回 1688 原圖")
        return []
    gen = [cover] if cover else []
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


def ai_cache_path(entry: dict, tpl_tag: str = "") -> Path:
    """文案快取檔：一列名單一份。

    ⚠️ 不可只用 1688 網址當 key（2026-09-17 抓到）：同一個網址常被名單多列用——
    HNV2／HNV5 是兩個編號、HNV11 三列（吸塵器／二合一／濾網）用款式備註挑不同款——
    舊版全擠同一份快取，第二列起直接沿用第一列的標題與挑款結果，
    HNV5 標題＝HNV2、HNV11 三個選項全變成 G1S 吸塵器，而且沒有任何錯誤訊息。
    """
    import hashlib
    item_id = str(entry["item_id"])
    code = re.sub(r"[^\w-]", "_", str(entry.get("code", "") or item_id))
    key = "|".join(str(entry.get(k, "") or "") for k in ("code", "name", "style_filter", "colors"))
    h = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    base = f"ai_content_{tpl_tag}" if tpl_tag else "ai_content"
    return Path(RAW_DIR) / item_id / f"{base}__{code}_{h}.json"


def cache_is_fresh(path: Path, sp) -> bool:
    """快取存在、而且是現行詳情／標題規則產的（規則改了換版號就會變成不新鮮）。"""
    if not path.exists():
        return False
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    if sp.detail_version and d.get("detail_version") != sp.detail_version:
        return False
    if sp.title_version and d.get("title_version") != sp.title_version:
        return False
    return True


def _prepare_product(entry: dict, json_dir: Path, shop: str = "lady",
                     shared_offer: bool = False, sop_override: list[str] | None = None,
                     img_template: str | None = None) -> dict | None:
    """把一個 manifest 商品項處理成 generate_batch_two_tier_excel 需要的 dict。"""
    from scraper.shops import channels_for, get_shop

    sp = get_shop(shop)
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
    item_dir = Path(RAW_DIR) / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    # ⚠️ 換文案模板＝不同產物，快取要分開存（否則選了新模板卻讀到舊模板的快取）
    tpl_tag = _template_tag(sop_override)
    ai_cache = ai_cache_path(entry, tpl_tag)
    cached = json.loads(ai_cache.read_text(encoding="utf-8")) if ai_cache.exists() else None
    if cached and sp.detail_version and cached.get("detail_version") != sp.detail_version:
        logger.info(f"[{code}] 快取文案是舊的詳情規則（{cached.get('detail_version') or '8 區塊'}）→ 重生")
        cached = None
    if cached and sp.title_version and cached.get("title_version") != sp.title_version:
        logger.info(f"[{code}] 快取文案是舊的標題規則（{cached.get('title_version') or '舊版'}）→ 重生")
        cached = None
    if entry.get("reuse_content") and cached:
        ai_content = cached
        logger.info(f"[{code}] 使用快取文案")
    else:
        ai_content = generate_listing(product_data, {
            "code": code,
            "selling_price": entry.get("price", ""),
            "demand": entry.get("demand", ""),
            "category": entry.get("category", ""),
            "style_note": entry.get("style_filter", ""),  # 第一層：Edwin 的款式備註
            "product_name": entry.get("name", ""),        # 名單品名 → 搜尋詞庫分類判斷
        }, shop=shop, sop_override=sop_override)
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

    # ── 顏色：明確 colors 覆寫 > 賣場政策 ──
    # lady（clothing）＝兩層篩選（款式備註 → 中性色 ≤5）；
    # nail/baby（cap_only）＝色號/花色是商品本體不砍色，只守 SKU 上限（超過從尾端截）。
    color_flag = None
    if entry.get("colors"):
        # 手動指定顏色（如舊 P-a1 --colors）→ 照填，不套政策
        selected_colors, color_map = _parse_colors(entry["colors"], color_map)
    else:
        # 第一層：Claude 依款式備註留下的第一軸選項（沒有就全部）
        all_keys = list(color_map.keys())
        kept = ai_content.get("style_kept") or []
        kept = [k for k in kept if k in color_map] or all_keys  # 對不上就退回全部
        if sp.color_policy == "clothing":
            # 第二層：第一軸＝顏色×身高款；身高款當尺寸全留，只砍底色到中性 ≤N，sku_cap 保底。
            pick = select_first_axis(kept, color_map, n_sizes,
                                     max_base_colors=sp.max_base_colors, sku_cap=sp.sku_cap)
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
        else:  # cap_only
            max_colors = max(1, sp.sku_cap // n_sizes)
            selected_colors = kept[:max_colors]
            if len(kept) > max_colors:
                color_flag = (f"選項 {len(kept)} × {n_sizes} 尺碼超過 {sp.sku_cap} SKU 上限，"
                              f"只留前 {max_colors} 個（要挑哪些請在名單 colors 欄指定）")
                logger.warning(f"[{code}] {color_flag}")

    variants = build_variants(code, short_name, color_map,
                              selected_colors, size_labels, selected_sizes)

    # 標題 v2.2 程式檢查（Nail）：能機械判斷的直接修、要判斷的大聲講（快取只存 AI 原文）
    if sp.title_version:
        from scraper.keyword_pool import banned_words, category_of, needs_pif
        from scraper.title_check import check_title
        name = entry.get("name", "") or short_name
        try:
            banned = banned_words()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{code}] 搜尋詞庫讀不到，標題不檢查泛用／他牌／死詞：{e}")
            banned = set()
        spec_src = [entry.get("name", ""), entry.get("style_filter", ""),
                    json.dumps(product_data.get("attributes", {}), ensure_ascii=False)]
        spec_src += [c.get("src_1688", "") for c in variants.get("規格1_顏色", [])]
        spec_src += [c.get("option_name", "") for c in variants.get("規格1_顏色", [])]
        spec_src += [s_.get("option_name", "") for s_ in variants.get("規格2_尺碼", [])]
        new_title, fixed, warns = check_title(
            ai_content.get("title", ""), code=code,
            pif=needs_pif(category_of(name, product_data.get("title", "")), name),
            banned=banned, spec_sources=spec_src)
        for f_ in fixed:
            logger.info(f"[{code}] 標題自動修正：{f_}")
        for w_ in warns:
            logger.warning(f"[{code}] ⚠️ 標題要人看：{w_}")
        ai_content = {**ai_content, "title": new_title, "title_warnings": warns}

    # 詳情＝AI 三段＋程式款式說明＋固定注意事項（Nail；快取只存 AI 那一半）
    if sp.detail_rule:
        from scraper.detail_builder import assemble_description
        ai_content = {**ai_content, "description": assemble_description(
            ai_content.get("description", ""), variants, str(entry.get("category", "")),
            short_name=f"{entry.get('name', '')} {short_name}".strip(),
            title_1688=product_data.get("title", ""))}

    # ⚠️⚠️ 第二軸漏掉的守門員（Edwin 2026-09-09 指出）：我們的第二軸只認商品屬性表的
    #    「尺码」那一列。頁面若是「色票 × 功率／型號／套餐」這種第二個下拉選單，
    #    第二軸會整個漏掉 → SKU表 M 規格二 空著 → 下單時 cart_adder 只點第一層，
    #    **訂到錯的規格而且不報錯**（同「缺貨被誤標成規格不符」那種假訊號）。
    #    抓取器現在會回 axis_labels，頁面明明有兩軸而我們只有一軸就大聲喊。
    _axes = [a for a in (product_data.get("axis_labels") or []) if a]
    if len(_axes) >= 2 and not variants.get("規格2_尺碼"):
        logger.warning(
            f"[{code}] ⚠️ 1688 頁面有 {len(_axes)} 軸規格（{'／'.join(_axes)}），"
            f"但我們只抓到第一軸 → SKU表 M 規格二 會是空的。"
            f"**下單時只會點第一層，可能訂到錯的規格且不會報錯**——"
            f"貼進 1-1 前請自行確認 M 欄，或先別讓這支走自動訂貨")

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
            ai_content.get("product_short_name") or product_data.get("title", ""),
            shop=shop, img_template=img_template)

    return {
        "product_data": product_data,
        "ai_content": ai_content,
        "variants": variants,
        "config": {
            "category": str(entry.get("category", "")),
            "selling_price": entry.get("price", 99),      # 掛牌價 → 蝦皮 Excel M 欄
            # 實際成交價（折後）→ 1-1 商品表 G；沒填就退回掛牌價並在 staging 警告
            "final_price": entry.get("final_price") or 0,
            "cost_cny": entry.get("cost_cny", ""),      # 名單填的 1688 進價（優先於抓取價）
            "stock_per_option": entry.get("stock"),   # 預購 200／現貨＝安全存量（見 ai_list_reader）
            # 重量：名單填了就用名單的，否則抓 1688 頁面的重量表。
            # ⚠️ 兩者都沒有 → None，Excel 留空並 warning，**不退回寫死的 0.1kg**
            #    （假重量會讓蝦皮運費與獲利表的結構版國際運費一起算錯且看起來像真的）
            "weight": entry.get("weight") or weight_kg(product_data, code, shared_offer),
            # 長/寬/高（cm）：比重量可靠（HNV7 重量是哨兵值、尺寸卻是真的），
            # 材積同樣是運費依據 → 有就填
            "dims_cm": dims_cm(product_data, code),
            "code": code,
            "size_chart_url": entry.get("size_chart_url", ""),  # Q 欄圖片尺寸表
            "image_skip": entry.get("image_skip", []),          # 排除的主圖 index（如有簡體字）
            "pre_order_days": entry.get("pre_order_days"),       # AP 較長備貨天數
            # 1-1 建檔用（master_staging 讀）：AI 名單新增的兩欄 + 預購/現貨
            "subcategory": entry.get("subcategory", ""),          # → 商品表 C 子分類
            "tag": entry.get("tag", ""),                          # → SKU表 D 標籤
            "demand": entry.get("demand", ""),                    # 預購/現貨 → 決定標籤與建檔分支
            "image_urls": image_urls,                            # ✨ GPT 生圖圖床 URL（有=覆蓋 1688）
            # 賣場差異（shops.py）：規格軸名 + 啟用的物流頻道
            # ⚠️ 一軸商品不一定是顏色：機器/工具類的那一軸是「規格」（美规/欧规），
            #    照 sp.axis1_name 寫死會讓前台顯示「顏色：美甲吸塵器_美規」。
            #    依 1688 原始屬性名判斷（实测 HNV7 集塵器）。
            "axis1_name": _axis1_name_for(product_data, sp),
            "axis2_name": sp.axis2_name,
            # 現貨多開「蝦皮店到店－隔日到貨」；預購不可開（shops.channels_for）
            "enabled_channels": channels_for(sp, entry.get("demand", "")),
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
    item_dir = Path(RAW_DIR) / item_id
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


def assemble_upload_assets(code: str, item_id: str, batch_dir: Path | None = None) -> Path | None:
    """把「要手動補到蝦皮」的素材（影片 + 尺寸表）按編號歸到一個好找的資料夾。

    產出 {這批的資料夾}/素材/{編號}/：
      {編號}_影片.mp4     ← 蝦皮商品影片（大量上架 Excel 沒影片欄，手動補）
      {編號}_尺寸表.png   ← 繁體尺寸表（若有；上傳蝦皮後可取得網址填 Q 欄）

    直觀用法：上架某商品時，打開 output/上架素材/{編號}/ 把裡面的東西補上蝦皮即可。
    """
    import shutil

    item_dir = Path(RAW_DIR) / item_id
    # ⚠️ 素材要跟著「批次」不是跟著「編號」：同一支商品改版重跑會產新影片，
    #    放 output/上架素材/{編號} 會直接蓋掉上一版、事後分不出哪個是哪次上架用的。
    dest = (Path(batch_dir) if batch_dir else Path(OUTPUT_DIR)) / "素材" / code
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


def _template_tag(sop_override: list[str] | None) -> str:
    """模板檔名 → 短標記（給快取檔名與 manifest 用）。沒指定回空字串＝該賣場預設。"""
    if not sop_override:
        return ""
    return Path(sop_override[0]).stem.replace(" ", "")[:24]


def _next_version_dir(batch_dir: Path, kind: str = "文案") -> tuple[Path, int]:
    """這批的下一個版本夾：{批次夾}/{kind}_v{N}/。

    ⚠️ **永不覆蓋舊版**（Edwin 2026-09-14）：「你不能確定版本二比版本一好，如果三個版本
    都不如預期，有可能直接採用版本一重新上傳」。所以每次產出一律開新號，舊的整份留著。
    文案與圖片各自編號——圖片不滿意重生時，文案可能是好的，不該被迫一起重跑。
    """
    n = 1 + max([int(d.name.rsplit("_v", 1)[1])
                 for d in batch_dir.glob(f"{kind}_v*") if d.is_dir()
                 and d.name.rsplit("_v", 1)[-1].isdigit()] or [0])
    d = batch_dir / f"{kind}_v{n}"
    d.mkdir(parents=True, exist_ok=True)
    return d, n


def _append_batch_note(batch_dir: Path, *, 版本: str, 模板: str, 範疇: str,
                       產出: list[str], 說明: str = "") -> None:
    """把這次產出追加到「批次說明.md」。

    Edwin 2026-09-14：「點進去批次檔就可以知道 9/9 生出的這批，文案 1 是用什麼方式建的、
    文案 2 是用什麼方式建的、素材是用什麼方式建的」——所以這份不是流水帳，要寫得下
    **每一版的建法**：用哪份規範、涵蓋哪些商品、產出哪些檔案。
    最後的「評語」留白給他自己標 OK / NG，挑版重傳時只看這一份。
    """
    f = batch_dir / "批次說明.md"
    if not f.exists():
        f.write_text(
            f"# {batch_dir.parent.name} / {batch_dir.name} 批次\n\n"
            "每產出一次就追加一段，**舊版一律保留**。\n"
            "「評語」自己填 OK / NG；之後要挑哪一版重傳，看這份就夠。\n\n"
            "---\n\n", encoding="utf-8")
    ts = datetime.now().strftime("%m/%d %H:%M")
    lines = [f"## {版本}　（{ts}）\n",
             f"- **怎麼建的**：{模板}\n",
             f"- **範疇**：{範疇}\n",
             f"- **產出**：{'、'.join(產出) if 產出 else '（無）'}\n"]
    if 說明:
        lines.append(f"- **備註**：{說明}\n")
    lines.append("- **評語**：\n\n")
    with f.open("a", encoding="utf-8") as fh:
        fh.write("".join(lines))


def _write_manifest(batch_dir: Path, shop: str, prepared: list[dict], failures: list[dict],
                    excel_path: Path, staging_result: dict | None,
                    version: str = "", template: str = "") -> Path:
    """這一批做了什麼，寫成一份 manifest.json 留在批次夾裡。

    為什麼要：事後問「HNV7 哪天上的、對應哪個 1688 連結、配到哪些品號」，翻這份就有答案，
    不必從 1-1 反推或憑記憶。**編號 ↔ item_id ↔ 品號** 三者的對照只有這裡完整記著。
    """
    items = []
    for p in prepared:
        m = p.get("_meta", {})
        items.append({
            "code": m.get("code"),
            "item_id": m.get("item_id"),
            "title": m.get("title"),
            "sku_count": m.get("sku_count"),
            "skus": sorted((p.get("config") or {}).get("option_sku_map", {}).values()),
            "video": str(m.get("video")) if m.get("video") else None,
        })
    doc = {
        "shop": shop,
        "版本": version,
        "文案模板": template,
        "產出時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "上架檔": Path(excel_path).name,
        "成功": len(prepared),
        "失敗": len(failures),
        "待貼新品": {"商品": staging_result.get("written"), "SKU": staging_result.get("sku_rows")}
                    if staging_result else None,
        "商品": items,
        "失敗明細": failures,
    }
    out = Path(batch_dir) / "manifest.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"manifest → {out}")
    return out


def run_batch_two_tier(
    manifest_path: Path | None = None,
    json_dir: Path = RAW_DIR,
    output_path: Path | None = None,
    template_path: Path | None = None,
    make_video: bool = True,
    video_n: int = 9,
    products: list[dict] | None = None,
    shop: str = "lady",
    make_staging: bool = False,
    staging_force: bool = False,
    sop_override: list[str] | None = None,
    img_template: str | None = None,
) -> dict:
    """逐商品處理（文案+變體，選配影片）→ 合併蝦皮二階 Excel。

    輸入二擇一：manifest_path（JSON 檔）或 products（清單，如 ai_list_reader 的輸出）。
    shop 決定：模板檔（各賣場自己下載的那份，hash 不同不可混用）、文案 SOP、
    選項政策、物流頻道、輸出檔名（scraper/shops.py）。
    make_staging=True（正式新品）：Excel 之外，另把商品寫進該賣場 1-1 的
    「_待貼新品」暫存分頁（master_staging），供人補編號後貼進商品表/SKU表。
    """
    from scraper.shops import get_shop

    sp = get_shop(shop)
    if products is not None:
        entries = products
        tpl = template_path or sp.template_path()   # 缺該賣場模板時這裡直接報清楚
    else:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        entries = manifest.get("products", [])
        tpl = template_path or (
            Path(manifest["template"]) if manifest.get("template") else sp.template_path()
        )
    if not entries:
        logger.warning("沒有商品可處理")
        return {"total": 0, "success": 0, "failed": 0, "excel_path": None, "failures": []}
    logger.info(f"賣場：{shop}（模板 {tpl.name}）")

    # 現貨沒填安全存量 → 整批不做（試跑不擋：那份檔本來就不能上架）
    if make_staging:
        from scraper.ai_list_reader import missing_safety_stock, missing_stock_message
        miss = missing_safety_stock(entries)
        if miss:
            raise ValueError(missing_stock_message(miss))

    # 這一批的資料夾：batch/{shop}/{YYYYMMDD}/，底下每跑一次開一個 文案_vN（舊版永不覆蓋）
    batch_dir = Path(BATCH_DIR) / shop / datetime.now().strftime("%Y%m%d")
    batch_dir.mkdir(parents=True, exist_ok=True)
    ver_dir, ver_no = _next_version_dir(batch_dir, "文案")
    tpl_name = _template_tag(sop_override) or "預設"
    logger.info(f"這批：{batch_dir.name} / 文案_v{ver_no}（模板 {tpl_name}）")
    if ver_no > 1:
        logger.warning(f"⚠️ 這是第 {ver_no} 版。傳之前先去蝦皮「待上架區」把上一版那批刪掉，"
                       f"否則會多一筆重複的（蝦皮不會依商品貨號覆蓋）")

    # 同一個 1688 網址被名單多列共用（會被拆成多個蝦皮商品）→ 影響重量的可信度
    _offer_uses = Counter(str(e.get("item_id")) for e in entries)

    prepared, failures, with_assets = [], [], []
    for entry in entries:
        code = entry.get("code", entry.get("item_id"))
        logger.info(f"{'='*50}\n處理 {code} (item_id: {entry.get('item_id')})")
        try:
            p = _prepare_product(entry, json_dir, shop=shop,
                                 shared_offer=_offer_uses[str(entry.get("item_id"))] > 1,
                                 sop_override=sop_override, img_template=img_template)
            if p is None:
                failures.append({"code": code, "error": "缺 JSON 或文案失敗"})
            else:
                if make_video:
                    p["_meta"]["video"] = _make_video_for(p, video_n)
                with_assets.append((p["_meta"]["code"], p["_meta"]["item_id"]))
                prepared.append(p)
        except Exception as e:
            logger.error(f"[{code}] 例外：{e}")
            failures.append({"code": code, "error": str(e)})

    # 素材（影片／尺寸表／GPT 生圖）走**自己的版本線**：圖不滿意重生時，文案可能是好的，
    # 不該被迫跟著重跑；所以 文案_vN 與 素材_vN 各自編號。
    # ⚠️ 先探有沒有東西可搬再開資料夾——上一版每支都先 mkdir，結果留下 28 個空夾。
    asset_ver, asset_no = None, 0
    used_gpt = False
    for code, item_id in with_assets:
        src = Path(RAW_DIR) / item_id
        gen = src / "images" / "generated"
        gpt = list(gen.glob("gpt_*.png")) if gen.exists() else []
        used_gpt = used_gpt or bool(gpt)
        has = ((src / "video" / f"{code}.mp4").exists()
               or (gen / f"size_chart_{code}.png").exists()
               or bool(gpt))
        if not has:
            continue
        if asset_ver is None:
            asset_ver, asset_no = _next_version_dir(batch_dir, "素材")
        assemble_upload_assets(code, item_id, asset_ver)
    if asset_ver is not None:
        _append_batch_note(
            batch_dir,
            版本=f"素材_v{asset_no}",
            模板=("GPT 生圖" if used_gpt else "1688 原圖合成"),
            範疇=f"{len(list(asset_ver.glob('*')))} 支商品的影片／尺寸表",
            產出=[f"素材_v{asset_no}/{{編號}}/"],
            說明="蝦皮大量上架 Excel 沒有影片欄，影片要在後台手動補")

    if not prepared:
        logger.warning("沒有成功處理的商品，不產生 Excel")
        return {"total": len(entries), "success": 0, "failed": len(failures),
                "excel_path": None, "failures": failures}

    if output_path is None:
        # 每批一夾 → 舊批次的上架檔不會被蓋掉。沒建檔＝沒配品號，檔名直接標「試跑」——
        # 這種檔上架後獲利表會對不到成本與銷量，而且不會有任何錯誤訊息，只能靠檔名擋住人手。
        output_path = ver_dir / ("上架檔.xlsx" if make_staging else "上架檔_試跑.xlsx")
    # ⚠️ 順序：**先配號再產 Excel**。Excel 的 O 商品選項貨號要填 SKU 品號，
    #    而品號是建檔那一步配的（讀 1-1、append-only）。舊版是 Excel 先產、建檔後跑
    #    → O 欄只能填 `HNV7_美規`，而獲利表是拿「蝦皮選項貨號 ＝ SKU 品號」去 join
    #    進貨成本與銷量的 → 這批商品的生意在獲利表裡會是黑的。
    staging_plan = None
    if make_staging:
        from scraper.master_staging import option_sku_maps, plan_blocks
        logger.info("先讀 1-1 配 SKU 品號（不寫入），讓 Excel 與待貼分頁用同一份號碼")
        staging_plan = plan_blocks(shop, prepared)
        maps = option_sku_maps(staging_plan[2])
        for i, p_ in enumerate(prepared):
            p_.setdefault("config", {})["option_sku_map"] = maps.get(i, {})
        n = sum(len(v) for v in maps.values())
        logger.info(f"配到 {n} 個 SKU 品號")

    generate_batch_two_tier_excel(prepared, Path(output_path), tpl)

    staging_result = None
    if make_staging:
        from scraper.master_staging import write_staging
        # 失敗不吞：Excel 已產好，但正式新品少了待貼分頁＝訂貨鏈路斷頭，要大聲讓人知道
        staging_result = write_staging(shop, prepared, force=staging_force)
        logger.info(f"待貼分頁：{staging_result['written']} 商品 / "
                    f"{staging_result['sku_rows']} SKU 列 → 1-1「{staging_result['tab']}」")

    _write_manifest(ver_dir, shop, prepared, failures, output_path, staging_result,
                    version=f"文案_v{ver_no}", template=tpl_name)
    _append_batch_note(
        batch_dir,
        版本=f"文案_v{ver_no}",
        模板=(f"文案模板「{tpl_name}」" if tpl_name != "預設" else "該賣場預設的文案規範"),
        範疇=f"{len(prepared)} 支商品"
             + (f"（失敗 {len(failures)} 支）" if failures else "")
             + "｜" + ("有建檔：配了 SKU 品號、寫了 1-1 待貼新品" if make_staging
                       else "⚠️ 沒建檔＝試跑，這版的上架檔不可上傳"),
        產出=[Path(output_path).name, "manifest.json"],
        說明=("上架前先去蝦皮待上架區刪掉上一版，否則會多一筆重複的" if ver_no > 1 else ""))

    # 上架核對表（Edwin 2026-09-17 定版）：試跑不寫；失敗不擋（上架檔已產好），但要喊出來
    check_result = None
    if make_staging:
        try:
            from scraper.listing_check import sync_check_sheet
            check_result = sync_check_sheet(shop, Path(output_path), prepared, f"文案_v{ver_no}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"⚠️ 上架核對表沒寫進去（{e}）——上架檔已產好，員工核對表要手動補或重跑")
            check_result = {"error": str(e)}

    summary = {
        "check_sheet": check_result,
        "total": len(entries),
        "success": len(prepared),
        "failed": len(failures),
        "excel_path": Path(output_path),
        "failures": failures,
        "products": [p["_meta"] for p in prepared],
        "staging": staging_result,
        "batch_dir": batch_dir,
        "version_dir": ver_dir,
        "version": f"文案_v{ver_no}",
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
