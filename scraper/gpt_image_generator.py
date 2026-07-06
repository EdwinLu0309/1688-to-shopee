"""
GPT 生圖（電商情境圖）— JoysLu Lady Images API Prompt System V1.0。

以 1688 原圖當參考圖編修（input_fidelity=high 保留實物衣服的面料/版型/顏色/細節），
套用品牌視覺語言產出「像精品女裝 lookbook」的電商圖。每張只講一個賣點（internal page）。

用法：
    from scraper.gpt_image_generator import generate_branded_images, PANTS_THEMES
    generate_branded_images(refs_by_theme, PANTS_THEMES, out_dir, product_ctx)
"""
import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

MODEL = "gpt-image-1.5"
SIZE = "1024x1024"      # 品牌規範：1:1 Square, Mobile First
QUALITY = "high"        # 精品感

# ── 品牌視覺語言（JoysLu Lady V2.0：穿搭 lookbook + 繁體特色標註）──────────────
# v2 更新：gpt-image-1.5 已能正確渲染中文（Edwin 實測），故不再禁中文、不再後製疊字，
# 直接讓 GPT 把「繁體特色標註」畫在圖上；風格從「極簡純圖」轉向「穿搭 lookbook + 賣點」。
BRAND = """You are a senior fashion art director for a premium women's fashion brand. Design a modern fashion
LOOKBOOK / editorial image in the styling language of Korean & Japanese fashion magazines and stylish 穿搭
lookbooks — the MODEL WEARS the garment in a real, aspirational lifestyle scene with genuine styling (nice
outfit pairing, natural setting, editorial mood). Tasteful, elegant, warm — not an empty product-only shot,
and NOT a marketplace promo.

COMPOSITION: 1:1 square. The styled model wearing the product is the hero (60-80% of canvas). Editorial
magazine layout with intentional negative space reserved for the caption text.

TEXT — RENDER CLEARLY (this is important): include ONE elegant Traditional-Chinese (繁體中文, Taiwan wording)
FEATURE CAPTION that highlights the selling point given below, set in a thin refined magazine-grade font,
plus optionally a small English label or 1-2 short keywords. Typography must be clean, minimal, beautifully
integrated like a fashion editorial caption — NOT stickers, NOT badges. Render every Chinese character
accurately, legibly and with correct strokes; never garbled.

COLOR / LIGHT: warm white / cream / beige / soft gray palette; natural daylight; soft shadow; boutique
editorial lighting. Never saturated colors, no fake lens flare.

GARMENT (critical): keep the EXACT garment from the reference photo — same fabric, fit, cut, color, pleats,
stitching, texture. MODEL: natural, relaxed, elegant lifestyle pose — never sexy, never runway.

STRICTLY FORBIDDEN: Taobao / Temu / Pinduoduo discount style, price tags, coupons, promo badges, sale
stickers, arrows, explosions, speech bubbles, colorful icons, cartoon elements, busy collage, low-end
typography, garbled text. Each image tells exactly ONE styling story below."""

# ── 下身類（寬褲）5 個主題：每張只講一件事 ───────────────────────────────
# (theme_key, 焦點 prompt, 建議英文標題, 中文副標)
PANTS_THEMES = [
    ("highwaist", "Focus ONLY on the HIGH WAIST design: how the high waistband elongates the legs and slims the "
                  "figure. Clean editorial half-body composition centered on the waist.",
     "HIGH WAIST", "高腰顯瘦"),
    ("fabric", "Focus ONLY on the ICE-SILK FABRIC: cool, airy, soft drape and subtle vertical texture. A serene "
               "close/mid shot letting the fabric texture breathe against warm white space.",
     "ICE SILK", "冰絲涼感"),
    ("drape", "Focus ONLY on the SILHOUETTE and soft DRAPE of the wide-leg cut: elegant vertical flow, full-length "
              "lookbook composition with generous margins.",
     "SOFT DRAPE", "垂墜寬褲"),
    ("daily", "Focus ONLY on a DAILY LIFESTYLE LOOK: an effortless everyday outfit, relaxed elegant lifestyle mood, "
              "natural setting, styling feeling.",
     "DAILY LOOK", "日常穿搭"),
    ("detail", "Focus ONLY on the refined DETAILS: waistband buttons and clean stitching, shown as a minimal, "
               "premium detail study with lots of whitespace.",
     "THE DETAILS", "質感細節"),
]


# 通用主題（非褲類 fallback：上衣/裙/外套皆可用）
GENERIC_THEMES = [
    ("silhouette", "Focus ONLY on the overall SILHOUETTE and how the garment falls on the body: elegant full "
                   "or half-body lookbook composition with generous margins.",
     "SILHOUETTE", "版型輪廓"),
    ("fabric", "Focus ONLY on the FABRIC quality: texture, drape and hand-feel, a serene mid/close shot letting "
               "the material breathe against warm white space.",
     "FABRIC", "面料質感"),
    ("detail", "Focus ONLY on the refined DETAILS (collar / cuff / hem / stitching), a minimal premium detail "
               "study with lots of whitespace.",
     "THE DETAILS", "質感細節"),
    ("daily", "Focus ONLY on a DAILY LIFESTYLE LOOK: an effortless everyday outfit, relaxed elegant mood, "
              "natural setting.",
     "DAILY LOOK", "日常穿搭"),
    ("styling", "Focus ONLY on STYLING: how to pair this piece into a complete elegant outfit, editorial "
                "full-look composition.",
     "STYLING", "穿搭示範"),
]

# 蝦皮分類 ID → 主題組（褲類走 PANTS，其餘走 GENERIC）
_PANTS_CATS = {"100358", "100360", "100361", "100103"}  # 長褲/短褲/褲裙/牛仔褲


def themes_for_category(category_id: str) -> list:
    return PANTS_THEMES if str(category_id) in _PANTS_CATS else GENERIC_THEMES


def generate_all(ref_paths: list[Path], out_dir: Path, product_name: str,
                 category_id: str = "") -> list[Path]:
    """一支商品：用同一組參考圖對每個主題各生一張。回傳本機 PNG 路徑清單。

    themes 依分類挑（褲/非褲）；refs 用商品的乾淨主圖（每個主題共用同一組）。
    """
    themes = themes_for_category(category_id)
    refs = [Path(p) for p in ref_paths if Path(p).exists()][:6]
    if not refs:
        logger.warning("無參考圖，無法生圖")
        return []
    refs_by_theme = {key: refs for key, *_ in themes}
    return generate_branded_images(refs_by_theme, themes, out_dir, product_name)


# ── v3 開放做法（Edwin 定案）：主圖+細節圖全丟進去，最少限制，讓 GPT 用自己的
# 電商理解出「女裝販售店會用的圖」，9 張一組，繁體不要簡體。不再框死美學/主題。
STORE_SYSTEM = (
    "These reference photos are ONE women's fashion product ({product}). You are an experienced "
    "e-commerce visual designer for a Taiwanese women's clothing online shop (蝦皮女裝專門店). "
    "Using your own understanding of what makes a strong fashion listing, create ONE polished, "
    "attractive, commercial listing image that a real women's-wear shop would actually use. "
    "Keep the EXACT garment (fabric, cut, color, drape, details). Any text MUST be Traditional "
    "Chinese (Taiwan wording) — absolutely NO Simplified Chinese and no garbled characters. "
    "Avoid cheap discount-marketplace clutter (no fake price tags, coupons, arrows, explosions)."
)

# 9 張的輕度分工（只給拍攝角度/用途建議，不框美學）——湊成一套完整賣場圖
STORE_ROLES = [
    "封面主圖：模特兒正面全身穿搭，乾淨吸睛，一眼看懂這件商品。",
    "情境穿搭：生活或街景實穿，自然有型的日常氛圍。",
    "側面或背面展示，讓買家看到版型與線條。",
    "面料質感特寫：帶出材質的垂墜與觸感。",
    "細節特寫：腰頭抽繩／口袋／車縫等做工。",
    "整體造型搭配示範：這件怎麼搭一套好看。",
    "坐姿或動態生活感，展現實穿舒適度。",
    "賣點說明圖：用簡潔繁體標出這款最強的 1-2 個特色。",
    "品牌氛圍形象圖：質感情境，提升整體檔次。",
]


def _edit(refs: list[Path], prompt: str, out_path: Path, fidelity: str = "high") -> Path | None:
    """核心：參考圖 + prompt → 生一張存檔。"""
    files = [open(p, "rb") for p in refs if Path(p).exists()]
    if not files:
        logger.warning("無參考圖，跳過")
        return None
    try:
        kwargs = dict(model=MODEL, image=files, prompt=prompt, size=SIZE, quality=QUALITY)
        try:
            resp = _client().images.edit(input_fidelity=fidelity, **kwargs)
        except TypeError:
            resp = _client().images.edit(**kwargs)  # 舊 SDK 無 input_fidelity
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(resp.data[0].b64_json))
        return out_path
    except Exception as e:  # noqa: BLE001
        logger.error(f"生圖失敗：{e}")
        return None
    finally:
        for f in files:
            f.close()


def generate_store_set(ref_paths: list[Path], out_dir: Path, product_name: str,
                       category_id: str = "", n: int = 9) -> list[Path]:
    """開放做法：主圖+細節圖當參考，最少限制出 n 張女裝賣場圖（繁體）。回傳本機路徑。"""
    refs = [Path(p) for p in ref_paths if Path(p).exists()][:12]
    if not refs:
        logger.warning("無參考圖，無法生圖")
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, role in enumerate(STORE_ROLES[:n]):
        prompt = STORE_SYSTEM.format(product=product_name) + f"\n\nTHIS IMAGE ({i+1}/{n}): {role}"
        out = _edit(refs, prompt, out_dir / f"store_{i+1:02d}.png")
        if out:
            results.append(out)
            logger.info(f"生圖 {i+1}/{n}：{out.name}")
    return results


def _client():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("缺少 OPENAI_API_KEY")
    from openai import OpenAI
    return OpenAI(api_key=key)


def generate_one(reference_images: list[Path], theme_prompt: str,
                 title: str, subtitle: str, product_name: str,
                 output_path: Path) -> Path | None:
    """用參考圖 + 主題 prompt 生一張品牌電商圖。"""
    client = _client()
    prompt = (
        f"{BRAND}\n\nPRODUCT: {product_name}.\n\nTHIS IMAGE: {theme_prompt}\n\n"
        f"FEATURE CAPTION to render on the image (Traditional Chinese, Taiwan, keep it short & elegant): "
        f"「{subtitle}」。 Optionally add a small English label \"{title}\". "
        f"Place the caption in the reserved negative space, thin elegant magazine typography, "
        f"accurate legible Chinese strokes — never covering the model's face or the garment."
    )
    files = [open(p, "rb") for p in reference_images if Path(p).exists()]
    if not files:
        logger.warning("無參考圖，跳過")
        return None
    try:
        kwargs = dict(model=MODEL, image=files, prompt=prompt, size=SIZE, quality=QUALITY)
        try:
            resp = client.images.edit(input_fidelity="high", **kwargs)  # 保留實物衣服
        except TypeError:
            resp = client.images.edit(**kwargs)  # 舊 SDK 無此參數
        b64 = resp.data[0].b64_json
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(b64))
        logger.info(f"生圖：{output_path}")
        return output_path
    except Exception as e:
        logger.error(f"生圖失敗（{title}）：{e}")
        return None
    finally:
        for f in files:
            f.close()


def generate_branded_images(refs_by_theme: dict, themes: list, out_dir: Path,
                            product_name: str) -> list[Path]:
    """對每個主題生一張。refs_by_theme[theme_key] = [參考圖路徑…]。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for key, theme_prompt, title, subtitle in themes:
        refs = refs_by_theme.get(key, [])
        out = generate_one(refs, theme_prompt, title, subtitle, product_name,
                           out_dir / f"gpt_{key}.png")
        if out:
            results.append(out)
    return results
