"""
用 Claude API 根據 1688 商品資料生成蝦皮上架內容。
"""
import os
import json

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SYSTEM_PROMPT = """你是一位專業的蝦皮（Shopee）台灣站商品上架文案專家。
根據提供的 1688 商品資料，生成適合台灣蝦皮上架的商品標題和商品描述。

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


def generate_shopee_content(product_data: dict, user_selections: dict | None = None) -> dict:
    """
    用 Claude 生成蝦皮上架內容。

    Args:
        product_data: 1688 爬取的商品 JSON
        user_selections: 使用者的選擇（分類、選的SKU、售價等）

    Returns:
        {"title": "...", "description": "..."}
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("缺少 ANTHROPIC_API_KEY")
        return {"title": "", "description": ""}

    client = anthropic.Anthropic(api_key=api_key)

    # 組裝給 Claude 的商品資訊
    info_parts = [
        f"商品名稱：{product_data.get('title', '')}",
        f"店鋪：{product_data.get('shop_name', '')}",
        f"品牌：{product_data.get('attributes', {}).get('品牌', '無品牌')}",
    ]

    # 價格
    price_ranges = product_data.get("price_ranges", [])
    if price_ranges:
        prices = [f"{pr['min_qty']}件起 ¥{pr['price']}" for pr in price_ranges]
        info_parts.append(f"1688 階梯價：{' / '.join(prices)}")

    # 屬性
    attrs = product_data.get("attributes", {})
    if attrs:
        attr_lines = [f"  {k}：{v}" for k, v in attrs.items()
                      if k not in ("颜色", "主要下游平台", "有可授权的自有品牌",
                                   "是否跨境出口专供货源")]
        info_parts.append("商品屬性：\n" + "\n".join(attr_lines[:15]))

    # SKU 選項
    skus = product_data.get("skus", [])
    if skus:
        sku_names = [s["attributes"].get("颜色", s["attributes"].get(list(s["attributes"].keys())[0], ""))
                     for s in skus[:20] if s.get("attributes")]
        info_parts.append(f"可選款式（共 {len(skus)} 種）：{', '.join(sku_names[:10])}...")

    # 使用者的選擇
    if user_selections:
        if user_selections.get("category"):
            info_parts.append(f"商品分類：{user_selections['category']}")
        if user_selections.get("selected_skus"):
            info_parts.append(f"上架款式：{user_selections['selected_skus']}")
        if user_selections.get("selling_price"):
            info_parts.append(f"台灣售價：NT${user_selections['selling_price']}")

    product_info = "\n".join(info_parts)

    logger.info("Calling Claude API for content generation...")
    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"請根據以下 1688 商品資料，生成蝦皮上架用的標題和描述：\n\n{product_info}"}
            ],
        )

        text = message.content[0].text.strip()
        # 嘗試解析 JSON
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        result = json.loads(text)
        logger.info(f"AI generated title: {result.get('title', '')[:50]}...")
        return result

    except json.JSONDecodeError:
        logger.warning(f"AI response not valid JSON, using raw text")
        return {"title": text[:80], "description": text}
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return {"title": "", "description": ""}
