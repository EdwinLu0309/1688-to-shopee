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

# ── 品牌視覺語言（JoysLu Lady V1.0，濃縮但忠實）────────────────────────────
BRAND = """You are a senior fashion art director for a PREMIUM women's fashion brand (not a marketplace seller).
Design this as a modern fashion LOOKBOOK image in the visual language of UNIQLO, GU, COS, Muji, Mercci22 —
elegant, minimal, soft, natural, timeless. The PRODUCT is the hero; typography only supports it; whitespace is
part of the design; less is more; luxury through simplicity.

COMPOSITION: 1:1 square. Product occupies 65-85% of canvas. Large clean margins, strong hierarchy, one clear
focal point, comfortable breathing space, no clutter. Editorial magazine / Swiss-minimal grid.

COLOR: background warm white / cream / light beige / soft gray. Accents only soft blue / light brown / taupe /
stone gray / black. NEVER saturated colors. LIGHT: natural daylight, soft almost-invisible shadow, boutique
editorial lighting — no dramatic or fake lens flare.

TYPOGRAPHY: thin, elegant, modern, generous spacing. VERY LITTLE text — at most an English title, a short
Chinese subtitle, and 1-3 keywords. No paragraphs, no marketing copy.

GARMENT (critical): keep the EXACT original garment from the reference photo — do NOT change its fabric, fit,
cut, color, pleats or stitching; maintain realistic fabric texture. MODEL: natural, relaxed, elegant, lifestyle
pose — never sexy, never runway.

STRICTLY FORBIDDEN: Taobao / Temu / Pinduoduo / discount style, promotional graphics, price labels, coupons,
badges, stickers, arrows, explosions, speech bubbles, colorful icons, cartoon elements, busy collage, fake
lens flare, low-end typography. Each image solves exactly ONE point below."""

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
        f"{BRAND}\n\nPRODUCT: {product_name}.\n\nTHIS IMAGE: {theme_prompt}\n"
        f"If any text appears, use ONLY the short English title \"{title}\" in a thin elegant font, "
        f"small and in a corner, never covering the product. "
        f"Do NOT render any Chinese characters or any other text (AI-rendered Chinese looks broken); "
        f"the Chinese subtitle will be added later by us."
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
