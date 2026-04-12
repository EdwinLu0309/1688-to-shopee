"""
用 Google Gemini API 生成蝦皮上架內容（標題、描述）+ 電商產品圖片。
取代原本的 ai_generator.py（Claude API）。
使用新版 google.genai SDK。
"""
import json
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from PIL import Image

load_dotenv()

from google import genai
from google.genai import types

from config.settings import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_IMAGE_MODEL

# 初始化 client
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── 蝦皮合規 System Prompt（從 ai_generator.py 移植） ──

SHOPEE_SYSTEM_PROMPT = """你是一位專業的蝦皮（Shopee）台灣站商品上架文案專家。
根據提供的 1688 商品資料和商品圖片，生成適合台灣蝦皮上架的商品標題和商品描述。

## 標題規則
- 繁體中文，50-80 字內，包含核心搜尋關鍵字
- 不要用 emoji
- 不要出現「現貨」「台灣現貨」「快速出貨」「隔日到貨」等出貨速度相關字眼

## 描述規則
- 繁體中文，結構化
- 只包含以下段落：
  1. 商品特色（賣點）
  2. 產品規格（容量、材質等客觀資訊）
  3. 適用場景或對象（如適用）
- 語氣：專業但親切，適合台灣消費者
- 不要直接翻譯中國用語，轉換為台灣習慣用法（如「發貨」→「出貨」、「质量」→「品質」）

## 絕對禁止出現的內容（蝦皮違規 + 業主規定）
- ❌ 產地、製造地、生產地（如「廣州」「中國製」「產地：XX」）— 完全禁止
- ❌ 出貨速度相關：「現貨」「隔日到貨」「快速出貨」「24小時出貨」「1-3天出貨」「台灣發貨」
- ❌ 注意事項段落 — 不要寫
- ❌ 出貨說明段落 — 不要寫
- ❌ 使用方法段落 — 不要寫（除非商品很特殊需要說明）
- ❌ 結尾行銷語（如「從選擇XX開始！」「趕快下單！」「限時優惠」）— 不要寫
- ❌ 導外聯絡方式：LINE、WhatsApp、微信、電話、email、任何站外聯繫方式
- ❌ 誘導站外交易：「私訊有優惠」「加好友享折扣」「站外購買更便宜」
- ❌ 其他平台名稱：淘寶、1688、天貓、拼多多、Amazon 等
- ❌ 虛假宣稱：「最好」「第一」「頂級」等絕對化用語
- ❌ 醫療宣稱：任何療效、治療、醫療相關聲明
- ❌ 不相關品牌標籤或關鍵字堆砌
- ❌ 價格相關誘導：「批發價」「工廠直銷」「成本價」

## 輸出格式
回傳 JSON：
{
  "title": "蝦皮商品標題",
  "description": "蝦皮商品描述（含換行）"
}
只回傳 JSON，不要其他文字。"""

# ── 電商圖片生成 Prompt ──

ECOMMERCE_IMAGE_PROMPT = """你是一位專業的電商產品圖片設計師。

根據以下商品資訊和原始產品圖片，生成適合蝦皮（Shopee）上架的電商產品圖片。

商品標題：{title}
商品描述：{description}

## 圖片要求
- 生成 3 張不同角度/風格的產品圖
- 風格：簡潔專業的電商風格
- 背景：白色或淺色乾淨背景
- 產品要清晰、佔畫面主體
- 可加入簡潔的中文賣點文字標註
- 圖片尺寸適合蝦皮（正方形 800x800 或 1:1 比例）
- 不要加入任何品牌 logo 或浮水印

請直接生成圖片。"""

# Rate limiting
_last_call_time = 0
_MIN_INTERVAL = 3  # 每次 API call 間隔最少 3 秒


def _rate_limit():
    """確保 API 呼叫間隔。"""
    global _last_call_time
    now = time.time()
    elapsed = now - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_time = time.time()


def _load_images_for_genai(image_paths: list[Path], max_images: int = 4) -> list:
    """載入圖片為 google.genai 可接受的 Part 格式。"""
    parts = []
    for path in image_paths[:max_images]:
        if not path.exists():
            continue
        try:
            img = Image.open(path)
            # 縮小太大的圖片以節省 token
            max_size = 1024
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            parts.append(img)
        except Exception as e:
            logger.warning(f"無法載入圖片 {path}: {e}")
    return parts


def _build_product_info(product_data: dict, user_config: dict | None = None) -> str:
    """組裝商品資訊文字。"""
    info_parts = [
        f"商品名稱：{product_data.get('title', '')}",
        f"店鋪：{product_data.get('shop_name', '')}",
        f"品牌：{product_data.get('attributes', {}).get('品牌', '無品牌')}",
    ]

    price_ranges = product_data.get("price_ranges", [])
    if price_ranges:
        prices = [f"{pr['min_qty']}件起 ¥{pr['price']}" for pr in price_ranges]
        info_parts.append(f"1688 階梯價：{' / '.join(prices)}")

    attrs = product_data.get("attributes", {})
    if attrs:
        skip_keys = {"颜色", "主要下游平台", "有可授权的自有品牌", "是否跨境出口专供货源"}
        attr_lines = [f"  {k}：{v}" for k, v in attrs.items() if k not in skip_keys]
        if attr_lines:
            info_parts.append("商品屬性：\n" + "\n".join(attr_lines[:15]))

    skus = product_data.get("skus", [])
    if skus:
        sku_names = []
        for s in skus[:20]:
            if s.get("attributes"):
                keys = list(s["attributes"].keys())
                name = s["attributes"].get("颜色", s["attributes"].get(keys[0], "")) if keys else ""
                sku_names.append(name)
        if sku_names:
            info_parts.append(f"可選款式（共 {len(skus)} 種）：{', '.join(sku_names[:10])}...")

    if user_config:
        if user_config.get("category"):
            info_parts.append(f"商品分類：{user_config['category']}")
        if user_config.get("selected_skus"):
            info_parts.append(f"上架款式：{user_config['selected_skus']}")
        if user_config.get("selling_price"):
            info_parts.append(f"台灣售價：NT${user_config['selling_price']}")

    return "\n".join(info_parts)


def generate_shopee_content(
    product_data: dict,
    image_paths: list[Path] | None = None,
    user_config: dict | None = None,
) -> dict:
    """
    用 Gemini 生成蝦皮上架的標題和描述（多模態：圖片+文字）。

    Returns:
        {"title": "...", "description": "..."}
    """
    if not client:
        logger.error("缺少 GEMINI_API_KEY")
        return {"title": "", "description": ""}

    product_info = _build_product_info(product_data, user_config)

    # 組裝多模態 prompt
    contents = []

    if image_paths:
        images = _load_images_for_genai(image_paths, max_images=4)
        contents.extend(images)

    contents.append(
        f"{SHOPEE_SYSTEM_PROMPT}\n\n"
        f"請根據以下 1688 商品資料（以及上方的商品圖片），"
        f"生成蝦皮上架用的標題和描述：\n\n{product_info}"
    )

    _rate_limit()
    logger.info("呼叫 Gemini API 生成文案...")

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
        )
        text = response.text.strip()

        # 解析 JSON
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        logger.info(f"Gemini 生成標題: {result.get('title', '')[:50]}...")
        return result

    except json.JSONDecodeError:
        logger.warning(f"Gemini 回應非 JSON，使用原始文字")
        return {"title": text[:80] if text else "", "description": text or ""}
    except Exception as e:
        logger.error(f"Gemini API 錯誤: {e}")
        return {"title": "", "description": ""}


def generate_ecommerce_images(
    image_paths: list[Path],
    title: str,
    description: str,
    output_dir: Path,
    num_images: int = 3,
) -> list[Path]:
    """
    用 Gemini 生成電商產品圖片。

    Returns:
        生成的圖片路徑列表
    """
    if not client:
        logger.error("缺少 GEMINI_API_KEY")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    # 載入原始圖片
    images = _load_images_for_genai(image_paths, max_images=6)
    if not images:
        logger.warning("沒有可用的原始圖片，跳過圖片生成")
        return []

    # 組裝 prompt
    prompt = ECOMMERCE_IMAGE_PROMPT.format(title=title, description=description)
    contents = list(images) + [prompt]

    _rate_limit()
    logger.info(f"呼叫 Gemini API 生成電商圖片（送入 {len(images)} 張原圖）...")

    try:
        response = client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        generated_paths = []
        img_idx = 0

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                mime = part.inline_data.mime_type
                data = part.inline_data.data

                ext = ".png"
                if "jpeg" in mime or "jpg" in mime:
                    ext = ".jpg"
                elif "webp" in mime:
                    ext = ".webp"

                img_path = output_dir / f"generated_{img_idx:03d}{ext}"
                img_path.write_bytes(data)
                generated_paths.append(img_path)
                logger.info(f"已儲存生成圖片: {img_path}")
                img_idx += 1

        if not generated_paths:
            logger.warning("Gemini 回應中沒有圖片")

        logger.info(f"共生成 {len(generated_paths)} 張電商圖片")
        return generated_paths

    except Exception as e:
        logger.error(f"Gemini 圖片生成錯誤: {e}")
        return []
