"""
商品資產包產生器：以「商品」為單位，把每支商品整理成一個可累積的資產資料夾。

定位（2026-07-26 #S103 定案，全賣場通用）：
- **資產包 = 一個商品一個資料夾**，放在雲端硬碟（Google Drive，網頁版 Chat 的連接器直接讀）：
    {賣場}/商品資產/
    ├── _使用說明.md   ← 給網頁版 Chat 讀的協作說明（write_usage_doc）
    └── {編號}/
        ├── 商品卡.md    ← 本模組產：**100% 純廠商固定事實**＋商品賣點（產物，別直接改）
        ├── 商品賣點.json ← 賣點與重點（AI 讀圖初稿＋我們的見解；★可累積編輯的活檔）
        ├── 基礎圖/      ← 1688 原圖（下載進來）
        ├── 優化圖/      ← 自己/GPT 做好的（汰換 1688 爛圖；本模組只建空夾）
        ├── 影片/        ← 1688 影片
        └── raw.json     ← 1688 原始抓取 JSON（源頭底料）
- **商品卡只放固定事實**：會變動 / 我方決策的東西一律不寫進來——
    · 售價、蝦皮分類 ID（我方上架決策）→ 從商品主表核對，不寫死
    · 文案（Chat 生成、會二調）→ 之後有自己的資產位置
    · 圖片影片 → 存資料夾，卡尾只指路
  這樣商品卡是「不變的地基」，其餘會動的各自成檔。

料源：`output/{item_id}.json`（1688 抓的）+ AI 名單 CSV（只為對到「編號」）。
"""
import json
import re
import shutil
from pathlib import Path

from loguru import logger

# 尺碼欄可能的 key（服飾第二軸）；其餘 attribute key 都當第一軸/一般屬性。
_SIZE_KEYS = ("尺码", "尺碼", "尺寸")

# 簡→繁（台灣正體 + 慣用詞）；lazy init，沒裝 opencc 就原樣回。
_cc = None


def _to_tw(text: str) -> str:
    """簡體轉繁體台灣用語。opencc 缺席時原樣回（URL/英數/編號不受影響，只轉漢字）。"""
    global _cc
    if _cc is None:
        try:
            import opencc
            # s2tw（純字形）不用 s2twp——後者會把「类型→型別」「项目→專案」等 IT 慣用詞
            # 替換掉，套在商品資料上會誤轉表頭與屬性名。
            _cc = opencc.OpenCC("s2tw")
        except Exception:
            _cc = False
    return _cc.convert(text) if _cc else text


# 給網頁版 Chat 讀的使用說明（寫在「商品資產」根目錄；每次產包時刷新）。
USAGE_DOC = """# 商品資產包 — 使用說明（給網頁版 Chat 先讀我）

每個子資料夾＝一個商品的資產包，**資料夾名＝商品編號**（如 `AAS1`）。

## 資料夾裡有什麼
| 檔案 | 是什麼 | 能不能改 |
|---|---|---|
| `商品卡.md` | 給人／你(Chat)讀的**成品**：純廠商固定事實（基本／特徵／選項／基礎數據）＋商品賣點 | ❌ **產物，別直接改**（重產會蓋掉） |
| `商品賣點.json` | 這個商品的**賣點與重點**（AI 讀詳情圖的初稿＋我們自己的見解） | ✅ **可以一直養的活檔，要改就改這個** |
| `raw.json` | 1688 原始抓取資料（源頭底料） | ❌ 只有重抓才更新 |
| `基礎圖/ 優化圖/ 影片/` | 圖片影片檔案 | 圖歸圖，不影響卡 |

## 你(Chat)該怎麼跟我(Edwin)協作 ★重要
1. 我會拿 `商品卡.md` 跟你討論標題／詳情／賣點。
2. 只要討論到**商品賣點有要修正或新增**（改掉不對的、補上我們自己的見解或客服常問點）：
   → **請主動問我：「要不要把這些更新直接覆寫進 `商品賣點.json`？」**
3. 我說「要」→ 你就產出**新版 `商品賣點.json` 的完整內容**（格式：`{"highlights": [...], "specs": {...}}`）給我覆寫。
4. `商品賣點.json` 一旦更新 → **`商品卡.md` 要跟著重生**：
   - 你可以照 `商品卡.md` 既有格式，用 `raw.json` ＋ 新版 `商品賣點.json` **重寫一份 `商品卡.md`** 給我；
   - 或提醒我回 CLI 跑 `python main.py product-cards --master --flat --items <編號> --out-base "<這個賣場的商品資產夾>"` 重產。

## 鐵則
- 修正**只寫進 `商品賣點.json`**（活檔）。**不要改 `商品卡.md`**（產物）、不要改 `raw.json`（源頭）。
- 重產有保護：跑 `--analyze` 時若 `商品賣點.json` 已存在會**跳過 AI、保護你的修正**（要 AI 重讀圖才加 `--force-analyze`）。
"""


def write_usage_doc(root: Path) -> None:
    """在「商品資產」根目錄寫／刷新使用說明（給 Chat 讀）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "_使用說明.md").write_text(USAGE_DOC, encoding="utf-8")


def _jin_to_kg(text: str) -> str:
    """尺碼字串裡的「斤」區間換算公斤（斤÷2）。無斤回空字串（美甲等非服飾就不顯示）。

    例：「S（80~95斤）」→「40~47.5 kg」；「100斤以内」→「≤50 kg」。
    """
    out = []
    for a, b in re.findall(r"(\d+(?:\.\d+)?)\s*[~～\-—到至]\s*(\d+(?:\.\d+)?)\s*斤", text):
        out.append(f"{_fmt(float(a) / 2)}~{_fmt(float(b) / 2)} kg")
    if out:
        return " / ".join(out)
    m = re.search(r"(\d+(?:\.\d+)?)\s*斤(以内|以內|左右|上下)?", text)
    if m:
        kg = _fmt(float(m.group(1)) / 2)
        suffix = m.group(2) or ""
        if suffix in ("以内", "以內"):
            return f"≤{kg} kg"
        return f"約 {kg} kg" if suffix else f"{kg} kg"
    return ""


def _fmt(x: float) -> str:
    """數字去尾零：47.5→'47.5'、40.0→'40'。"""
    return f"{x:g}"


def _sanitize(name: str) -> str:
    """資料夾/檔名清理。"""
    return re.sub(r'[\\/:*?"<>|]', "_", (name or "")).strip() or "unknown"


def _load_code_map(csv_path: Path | None) -> dict[str, str]:
    """讀 AI 名單 CSV → {item_id: 編號}。只為了對到編號（其餘我方欄位不進商品卡）。"""
    if not csv_path or not Path(csv_path).exists():
        return {}
    try:
        from scraper.ai_list_reader import parse_ai_list_csv
        rows = parse_ai_list_csv(Path(csv_path))
        return {r["item_id"]: r["code"] for r in rows if r.get("item_id") and r.get("code")}
    except Exception as e:
        logger.warning(f"讀 AI 名單失敗（{csv_path}）：{e}")
        return {}


def _price_ranges_str(product: dict) -> str:
    """階梯進貨價 → 一行。"""
    parts = []
    for pr in product.get("price_ranges") or []:
        mx = pr.get("max_qty", -1)
        rng = f"{pr.get('min_qty')}-{mx}" if mx and mx > 0 else f"{pr.get('min_qty')}+"
        parts.append(f"{rng} 件 ¥{pr.get('price')}")
    return "、".join(parts)


def _axis_keys(product: dict) -> tuple[list[str], str | None]:
    """從 skus 的 attribute 找出軸：回 (第一軸 keys, 尺碼軸 key)。

    通用化：軸標題直接用 1688 attribute 的 key 原名（美甲甲油膠→「颜色」/「色号」、
    光療燈→「规格」），不寫死「顏色×尺碼」。
    """
    keys: list[str] = []
    for s in product.get("skus", []):
        for k in (s.get("attributes") or {}).keys():
            if k not in keys:
                keys.append(k)
    size_key = next((k for k in keys if k in _SIZE_KEYS), None)
    first_axis = [k for k in keys if k != size_key]
    return first_axis, size_key


def _looks_like_size(vals: list[str]) -> bool:
    """值大多長得像服飾尺碼（S/M/L/XL/2XL/F/均碼/數字）才算尺碼軸。"""
    if not vals:
        return False
    pat = re.compile(r"^\s*(XS|S|M|L|XL|X?XL|[2-6]XL|F|均[码碼]|\d{1,3})\b")
    hit = sum(1 for v in vals if pat.match(str(v)))
    return hit >= max(1, len(vals) // 2)


def _axis2_title(product: dict, sizes: list[str], size_key: str | None, has_jin: bool) -> str:
    """第二軸標題（通用）：skus 有尺码 key 就用它；否則看是不是真尺碼，不是就叫「規格/選項」。

    修正真實案例（美甲燈 52 型號被誤標「尺碼」）：非服飾商品的買區選項不該硬叫尺碼。
    """
    if size_key:
        return size_key
    attrs = product.get("attributes", {}) or {}
    if has_jin or _looks_like_size(sizes):
        return "尺碼"
    if any(k in attrs for k in ("规格", "規格")):
        return "規格"
    return "選項"


def build_card_markdown(product: dict, code: str, highlights: dict | None = None,
                        supplier: str = "") -> str:
    """組「純廠商固定事實」商品卡 Markdown。只吃 1688 product + 編號（+ 圖片解析賣點 + 主表廠商）。"""
    item_id = product.get("item_id", "")
    url = f"https://detail.1688.com/offer/{item_id}.html" if item_id else ""
    attrs = product.get("attributes", {}) or {}
    name = product.get("title", "")

    _CN = "一二三四五六七八九十"
    _n = [0]

    def sec(title: str) -> str:
        _n[0] += 1
        return f"## {_CN[_n[0] - 1]}、{title}"

    L: list[str] = []
    L.append(f"# 商品卡｜{code or item_id}　{name}".rstrip())
    L.append("")
    L.append("> 純廠商固定事實（編號 + 1688 抓來的東西）。售價/分類/文案等會變動的另有位置，不寫這。")
    L.append("")

    # 基本資訊（只放固定的）
    L.append(sec("基本資訊"))
    L.append(f"- **編號**：{code or '（名單未對到）'}")
    L.append(f"- **1688 網址**：{url}")
    shop = product.get("shop_name", "")
    loc = product.get("shop_location", "")
    origin_place = attrs.get("产地") or attrs.get("產地") or ""
    if supplier:  # 主表廠商優先（抓取常抓不到店名）
        shop_line = supplier
    else:
        shop_line = "、".join(x for x in [shop, loc] if x)
        if not shop_line:
            shop_line = f"（店名未抓到，产地 {origin_place}）" if origin_place else "（未知）"
    L.append(f"- **廠商**：{shop_line}")
    origin = product.get("origin_price") or product.get("price_cny") or 0
    steps = _price_ranges_str(product)
    L.append(f"- **進貨價**：¥{origin}" + (f"（階梯：{steps}）" if steps else ""))
    if product.get("min_order"):
        L.append(f"- **起訂量**：{product.get('min_order')}")
    L.append("")

    # 商品特徵（1688 全屬性，照原順序原文，最忠實）
    L.append(sec("商品特徵（1688 屬性）"))
    if attrs:
        L.append("| 項目 | 內容 |")
        L.append("|---|---|")
        for k, v in attrs.items():
            if v:
                L.append(f"| {k} | {v} |")
    else:
        L.append("（無屬性資料）")
    L.append("")

    # 三、商品賣點（vision 解析詳情圖，賣點藏在圖裡、屬性表抓不到）
    highlights = highlights or {}
    hl = highlights.get("highlights") or []
    specs = highlights.get("specs") or {}
    if hl or specs:
        L.append(sec("商品賣點（AI 讀圖＋我們的見解）"))
        for h in hl:
            L.append(f"- {h}")
        if specs:
            L.append("")
            L.append("| 規格 | 值 |")
            L.append("|---|---|")
            for k, v in specs.items():
                L.append(f"| {k} | {v} |")
        L.append("")

    # 四、選項規格（軸名跟著 1688 實際 attribute 走）
    first_axis, size_key = _axis_keys(product)
    sku_images = product.get("sku_images") or {}
    L.append(sec("選項規格"))
    # 第一軸
    axis_title = "、".join(first_axis) if first_axis else ("選項" if sku_images else "")
    first_vals: list[str] = []
    if first_axis:
        seen = set()
        for s in product.get("skus", []):
            v = "／".join(str(s["attributes"][k]) for k in first_axis if k in s.get("attributes", {}))
            if v and v not in seen:
                seen.add(v)
                first_vals.append(v)
    if not first_vals and sku_images:
        first_vals = list(sku_images.keys())
    if first_vals:
        L.append(f"**{axis_title or '第一軸'}（{len(first_vals)}）**")
        L.append("")
        L.append(f"| {axis_title or '選項'} | 圖 |")
        L.append("|---|---|")
        for v in first_vals:
            img = sku_images.get(v, "")
            L.append(f"| {v} | {('![](' + img + ')') if img else ''} |")
        L.append("")
    # 尺碼軸
    size_stock = product.get("size_stock") or {}
    sizes = product.get("sizes") or (list(size_stock.keys()) if size_stock else [])
    has_jin = any(_jin_to_kg(s) for s in sizes)
    axis2 = _axis2_title(product, sizes, size_key, has_jin)
    if sizes:
        title = axis2
        L.append(f"**{title}（{len(sizes)}）**")
        L.append("")
        if has_jin:
            L.append(f"| {title} | 建議體重(斤÷2) |")
            L.append("|---|---|")
            for sz in sizes:
                L.append(f"| {sz} | {_jin_to_kg(sz)} |")
        else:
            L.append(f"| {title} |")
            L.append("|---|")
            for sz in sizes:
                L.append(f"| {sz} |")
        L.append("")
    if not first_vals and not sizes:
        L.append("（無選項軸——單一規格 / 均一款）")
        L.append("")

    # 四、基礎數據（各選項單價/庫存）
    skus = product.get("skus") or []
    L.append(sec("基礎數據（各選項 1688 單價 / 庫存）"))
    if skus:
        L.append("| 選項 | 單價(¥) | 庫存 |")
        L.append("|---|---|---|")
        for s in skus:
            opt = "／".join(f"{v}" for v in (s.get("attributes") or {}).values()) or s.get("sku_id", "")
            L.append(f"| {opt} | {s.get('price', '')} | {s.get('stock', '')} |")
    elif size_stock:
        L.append(f"| {axis2} | 單價(¥) | 庫存 |")
        L.append("|---|---|---|")
        for sz, st in size_stock.items():
            L.append(f"| {sz} | {st.get('price', '')} | {st.get('stock', '')} |")
    else:
        L.append("（無 SKU 層價格/庫存資料）")
    L.append("")

    # 圖片影片指路（檔案在資產包資料夾，卡不列 URL）
    n_main = len(product.get("main_images") or [])
    n_detail = len(product.get("detail_images") or [])
    has_video = bool(product.get("video_url"))
    L.append("---")
    L.append(f"> 📁 圖片影片見本資料夾：`基礎圖/`（主圖 {n_main}／細節 {n_detail}）、"
             f"`優化圖/`、`影片/`（{'有' if has_video else '無'}）")
    L.append("> ✏️ 要改賣點/重點 → 改本資料夾的 `商品賣點.json`（活檔），再重產本卡；"
             "別直接改本檔（產物會被覆蓋）。用法見同層 `_使用說明.md`。")
    L.append("")

    # 整卡簡轉繁（台灣用語）；URL/編號是英數不受影響
    return _to_tw("\n".join(L))


async def _download_media(product: dict, pack_dir: Path) -> dict:
    """下載 1688 主圖/細節/SKU 圖進 基礎圖/、影片進 影片/。回各類數量。"""
    from scraper.downloader import download_product_images_from_json

    res = await download_product_images_from_json(product, pack_dir / "基礎圖")
    counts = {k: len(v) for k, v in res.items()}
    # 影片
    video = product.get("video_url")
    if video:
        try:
            import httpx
            (pack_dir / "影片").mkdir(parents=True, exist_ok=True)
            with httpx.Client(timeout=60, follow_redirects=True) as c:
                # 1688 影片 CDN 不能帶 Referer，只帶 UA
                r = c.get(video, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and r.content:
                    (pack_dir / "影片" / f"{product.get('item_id','video')}.mp4").write_bytes(r.content)
                    counts["video"] = 1
        except Exception as e:
            logger.warning(f"影片下載失敗：{e}")
    return counts


def _find_source_images(pack: Path, item_id: str) -> list[Path]:
    """找詳情圖給 vision 讀（賣點多印在 detail；沒有就退 main）。
    先看資產包 基礎圖/{detail,main}，再退 output/{item}/images/{detail,main}（images 指令產的）。"""
    for root in (pack / "基礎圖", Path("output") / item_id / "images"):
        for sub in ("detail", "main"):
            files = sorted(p for p in (root / sub).glob("*.*")) if (root / sub).exists() else []
            if files:
                return files
    return []


def generate_asset_packs(
    json_dir: Path,
    shop: str,
    out_base: Path | None = None,
    ai_list_csv: Path | None = None,
    item_ids: list[str] | None = None,
    download_media: bool = False,
    analyze_highlights: bool = False,
    use_master: bool = False,
    sa_json: str | Path | None = None,
    shop_subdir: bool = True,
    force_analyze: bool = False,
) -> list[dict]:
    """批次產商品資產包。

    Args:
        json_dir:           放 {item_id}.json 的目錄（通常 output/）
        shop:               賣場代號（nail/lady/baby）→ 分子夾
        out_base:           資產根目錄（預設 json_dir/商品資產）。指向 Google Drive 即直接落雲端。
        ai_list_csv:        AI 名單 CSV（只為對編號；預設 input/lady_ai_list.csv 若存在）
        item_ids:           只產這些 item_id（None = 全部）
        download_media:     是否下載 1688 圖片/影片進資產包（預設 False，先只產卡+raw+空夾）
        analyze_highlights: 是否用 vision 讀詳情圖條列商品賣點（需 OPENAI_API_KEY + 有圖）
        use_master:         用商品主表當編號/廠商來源（資料夾名＝主表商品編號，跨系統一致）
        sa_json:            主表 SA 憑證路徑（use_master 時用；預設自動找）

    Returns:
        [{item_id, code, dir}] 每支一筆。
    """
    import asyncio

    json_dir = Path(json_dir)
    out_base = Path(out_base) if out_base else json_dir / "商品資產"
    # 雲端已按賣場分夾（1.【Nail】）→ --flat 不再加 nail/ 子夾；本機預設加
    shop_dir = out_base / shop if shop_subdir else out_base
    shop_dir.mkdir(parents=True, exist_ok=True)
    write_usage_doc(shop_dir)  # 給 Chat 讀的使用說明，跟各商品資料夾放一起

    # 編號來源：主表（權威，含廠商/分類）優先，否則退 AI 名單 CSV
    master: dict[str, dict] = {}
    code_map: dict[str, str] = {}
    if use_master:
        from scraper.master_reader import read_master
        master = read_master(sa_json=sa_json)
    else:
        if ai_list_csv is None:
            default_csv = Path("input") / "lady_ai_list.csv"
            ai_list_csv = default_csv if default_csv.exists() else None
        code_map = _load_code_map(ai_list_csv)

    json_files = sorted(p for p in json_dir.glob("*.json") if p.stem.isdigit())
    if item_ids:
        want = set(item_ids)
        json_files = [p for p in json_files if p.stem in want]

    results: list[dict] = []
    for jf in json_files:
        try:
            product = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"讀 {jf.name} 失敗：{e}")
            continue
        item_id = product.get("item_id", jf.stem)
        m = master.get(item_id, {})
        code = m.get("code") or code_map.get(item_id, item_id)
        supplier = m.get("supplier", "")
        pack = shop_dir / _sanitize(code)
        for sub in ("基礎圖", "優化圖", "影片"):
            (pack / sub).mkdir(parents=True, exist_ok=True)

        if download_media:
            counts = asyncio.run(_download_media(product, pack))
            logger.info(f"[{code}] 媒體下載：{counts}")

        # 商品賣點：一律先讀已存在的 商品賣點.json（帶 Edwin 的手動修正進商品卡）。
        # --analyze 只在「還沒有賣點檔」時才跑 vision；已存在就跳過保護（避免蓋掉修正）。
        # 真要重跑 vision 覆寫 → force_analyze=True。
        hl_path = pack / "商品賣點.json"
        highlights = None
        if hl_path.exists():
            try:
                highlights = json.loads(hl_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[{code}] 商品賣點.json 壞了：{e}")
        if analyze_highlights and (highlights is None or force_analyze):
            imgs = _find_source_images(pack, item_id)
            if imgs:
                try:
                    from scraper.auto_classify import extract_highlights
                    highlights = extract_highlights(imgs)
                    hl_path.write_text(
                        json.dumps(highlights, ensure_ascii=False, indent=2), encoding="utf-8")
                    logger.info(f"[{code}] 商品賣點 {len(highlights.get('highlights', []))} 條")
                except Exception as e:
                    logger.warning(f"[{code}] 賣點解析失敗：{e}")
            else:
                logger.warning(f"[{code}] 沒有圖片可解析賣點（先 --download-media 或跑 images）")
        elif analyze_highlights and highlights is not None and not force_analyze:
            logger.info(f"[{code}] 商品賣點.json 已存在，跳過 vision（保護修正；要重跑加 --force-analyze）")

        (pack / "商品卡.md").write_text(
            build_card_markdown(product, code, highlights, supplier=supplier), encoding="utf-8")
        # raw.json 只有「還沒有 或 有重抓新資料」才寫；預設不覆蓋（它是原始快照）
        raw_path = pack / "raw.json"
        if not raw_path.exists() or download_media:
            shutil.copyfile(jf, raw_path)

        results.append({"item_id": item_id, "code": code, "dir": str(pack)})
        logger.info(f"[{code}] 資產包 → {pack}")

    logger.info(f"共產出 {len(results)} 個商品資產包 → {shop_dir}")
    return results
