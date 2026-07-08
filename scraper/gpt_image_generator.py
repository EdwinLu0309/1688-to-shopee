"""
GPT 生圖 — JoysLu AI Design Engine V0.1（Edwin 定案）。

架構：**Claude 不理解設計**。設計規範全在 `config/design_engine/*.md`（Edwin 維護）。
本模組只負責：讀所有 md → 組圖（商品圖 + 1688 參考圖 + 品牌人物/板娘 + 對手場景參考）
→ 呼叫 GPT Images API。改規範＝改 md，不改這支程式。

圖片輸入（對應 design_engine/README）：
- 商品圖片：以此為準（商品真實，PRODUCT_RULES 明訂不得修改商品）
- 1688 參考圖：只參考角度/內容/細節，不得照抄
- 品牌人物圖（板娘，可選）：`design_engine/persona/`，讓 model 長相＝板娘風格
- 對手場景參考（可選）：`design_engine/reference/`，讓 GPT 學對手場景/動作/拍攝
"""
import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

MODEL = "gpt-image-1"   # Edwin 指定：用 gpt-image-1（chat 裡就是這顆在生圖），不用 DALL·E/1.5
SIZE = "1024x1024"      # 1:1，Mobile First
QUALITY = "high"

ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = ROOT / "config" / "design_engine"
PERSONA_DIR = DESIGN_DIR / "persona"       # 品牌人物（板娘）
REFERENCE_DIR = DESIGN_DIR / "reference"   # 對手場景參考

_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def _client():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("缺少 OPENAI_API_KEY")
    from openai import OpenAI
    return OpenAI(api_key=key)


def load_design_spec() -> str:
    """讀 design_engine 下所有 md（依檔名排序）串成規範文字。"""
    if not DESIGN_DIR.exists():
        raise RuntimeError(f"找不到設計規範資料夾：{DESIGN_DIR}")
    parts = []
    for md in sorted(DESIGN_DIR.glob("*.md")):
        txt = md.read_text(encoding="utf-8").strip()
        if txt:
            parts.append(txt)
    if not parts:
        raise RuntimeError(f"{DESIGN_DIR} 裡沒有任何 md 規範")
    return "\n\n".join(parts)


def _imgs(d: Path, n: int | None = None) -> list[Path]:
    if not d.exists():
        return []
    fs = sorted(p for p in d.glob("*") if p.suffix.lower() in _IMG_EXT)
    return fs[:n] if n else fs


def _normalize(paths: list[Path], workdir: Path) -> list[Path]:
    """把參考圖統一轉成乾淨 RGB PNG（+ 大圖縮到 1536）。避免舊照片 CMYK/怪模式
    被 gpt-image API 擋（invalid image file or mode）。轉檔失敗的個別跳過。"""
    from PIL import Image

    workdir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, p in enumerate(paths):
        try:
            im = Image.open(p).convert("RGB")
            m = max(im.size)
            if m > 1536:
                s = 1536 / m
                im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
            dst = workdir / f"in_{i:02d}.png"
            im.save(dst, "PNG")
            out.append(dst)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"參考圖 {Path(p).name} 轉檔失敗，跳過：{e}")
    return out


def _edit(images: list[Path], prompt: str, out_path: Path) -> Path | None:
    """核心：一組參考圖 + prompt（＝md 規範）→ 生一張存檔。"""
    norm = _normalize([Path(p) for p in images if Path(p).exists()],
                      out_path.parent / "_gpt_in")
    files = [open(p, "rb") for p in norm]
    if not files:
        logger.warning("無圖可餵，跳過")
        return None
    try:
        kwargs = dict(model=MODEL, image=files, prompt=prompt, size=SIZE, quality=QUALITY)
        try:
            resp = _client().images.edit(input_fidelity="high", **kwargs)
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


def generate_cover(product_images: list[Path], ref_1688_images: list[Path],
                   out_path: Path, persona_images: list[Path] | None = None) -> Path | None:
    """依 design_engine 規範產生第一張封面（Cover）。

    圖序：商品圖（以此為準）→ 1688 參考 → 品牌人物（板娘）→ 對手場景參考。
    persona/reference 沒放圖就自動略過（皆可選）。
    """
    spec = load_design_spec()
    persona = list(persona_images) if persona_images else _imgs(PERSONA_DIR, 3)
    refs = _imgs(REFERENCE_DIR, 3)
    # gpt-image edit 有輸入張數上限，控在 ~15 內；板娘臉給 3 張讓長相鎖得住
    product = list(product_images)[:6]
    ref1688 = list(ref_1688_images)[:3]
    images = product + ref1688 + persona[:3] + refs[:3]
    if not images:
        logger.warning("無任何參考圖，無法生圖")
        return None
    prompt = spec + "\n\n---\n請嚴格依上述規範，產生第一張「封面（Cover）」。"
    logger.info(f"GPT 生封面：{len(images)} 張參考"
                f"（商品 {len(product)} / 1688 {len(ref1688)} / 板娘 {len(persona[:3])} / 對手 {len(refs[:3])}）")
    return _edit(images, prompt, Path(out_path))
