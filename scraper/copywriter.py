"""
文案引擎：用 Claude + 各賣場 SOP 生成蝦皮上架文案（#S165 三賣場化）。

輸入：extract_1688.js 抓的兩軸商品資料 + 採購表脈絡（編號 / 售價 / 訂貨需求 / 分類）
輸出：商品簡稱 / 蝦皮標題 / 詳情頁 8 區塊 / 繁體顏色對照 / 尺碼標籤 / flags
      （變體選項名稱「編號_簡稱_顏色」由 build_variants() 用程式拼，不交給 LLM 確保精準）

賣場差異（品牌標籤/受眾詞/SOP 檔/尺碼規則/子品類）全部由 scraper/shops.py 的
profile 提供，generate_listing 帶 shop 參數；SOP 全文塞 system（config/sop/ 下 per-shop）。

大 SOP 走 Anthropic prompt cache（system 陣列 + cache_control），多商品連跑省 input。
⚠️ 同一批次混跑多賣場會讓 cache 失效（system 不同），批次請一次跑一個賣場。
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

SOP_DIR = Path(__file__).parent.parent / "config" / "sop"
MODEL = "claude-sonnet-4-6"

# system prompt 用「字串拼接」組（不用 .format）：SOP 全文若含大括號，.format 會炸。
_ROLE_HEAD = """你是{shop_desc}的上架文案專家。
嚴格遵守下方規範產出文案。核心心法：廠商有寫就用、沒寫套 fallback 或省略、
不腦補機能、不過度承諾、抓 80% 完整即可。所有文字一律繁體中文、台灣用語
（不可出現中國用語與簡體字，依字典轉換）。

下面是規範（務必遵守）：
"""

_TASK = """根據以下 1688 商品資料 + 賣場設定，產出蝦皮上架文案。

【賣場設定】
- 商品編號：{code}
- 蝦皮售價：NT${price}
- 訂貨需求：{demand}
- 蝦皮分類：{category}
- 款式備註（Edwin 指定這支要哪些款式/季節）：{style_note}

【1688 商品資料】
- 原始商品名：{title}
- 商品屬性：{attributes}
- 第一軸（顏色/款式，簡體原文）：{colors}
- 第二軸（尺碼）：{sizes}
- 1688 單價：¥{price_cny}

【要做的事】
0. 款式篩選（第一層）：依「款式備註」從第一軸選項挑出 Edwin 要的，列進 style_kept。
   - 備註排除某季節/款式（例：「不要加絨的冬天款，其他都需要」）→ 排除加絨/冬款選項、其餘保留。
   - 備註指定某款式（例：「只要長褲」）→ 只留該款式選項。
   - 備註空白或「全款式 / 全部顏色 / 全部」→ 第一軸「全部」原樣列入 style_kept。
   - style_kept 內容必須是第一軸的「原始選項名（簡體、照原文一字不差）」，不要改寫。
1. 判子品類（{subcategory_line}）
2. 商品簡稱：依商品名濃縮成 2-5 字繁體台灣用語（如「冰丝阔腿裤」→「冰絲寬褲」）
3. 蝦皮標題：{title_rule}
4. 完整詳情頁（通用 8 區塊全文，套規範固定文案：賣場介紹/退換貨/推薦三款）
5. 顏色簡繁對照：把每個第一軸顏色轉成繁體乾淨名（去掉廠商括號贅字，如「米白色【长裤】」→「米白色」；款式差異若需保留另說）
{size_rule}
7. flags：字典待擴充的新顏色/材質詞、廠商備註、疑似違規詞、子品類不確定、尺碼數據缺漏

【只回傳這個 JSON，不要任何其他文字】
{{
  "subcategory": "子品類",
  "product_short_name": "商品簡稱（繁體）",
  "title": "蝦皮標題",
  "description": "完整 8 區塊詳情頁文案（含換行）",
  "style_kept": ["依款式備註保留的第一軸原始選項名（簡體照原文）"],
  "color_map": {{"1688簡體顏色": "繁體乾淨顏色"}},
  "size_labels": {{"尺碼": "尺碼+公斤數據或純尺碼，如 S（40-47.5kg）；體重一律 kg 不可用斤"}},
  "flags": ["..."]
}}"""


def _build_system(sp) -> str:
    """組 system prompt：角色 + 該賣場全部 SOP 全文（字串拼接，SOP 含大括號也安全）。"""
    parts = [_ROLE_HEAD.format(shop_desc=sp.shop_desc)]
    for name, text in sp.sop_texts():
        parts.append(f"\n=== {name} ===\n{text}\n")
    return "".join(parts)


def _title_rule(sp) -> str:
    aud = f"+「{sp.audience_word}」" if sp.audience_word else ""
    rule = f"依 SOP 標題規則，含{sp.brand_tag}+ 核心關鍵字 {aud}+ 編號，57-60 字寬內。"
    return rule + (sp.title_extra or "")


def generate_listing(product_data: dict, sheet_ctx: dict, shop: str = "lady") -> dict:
    """
    生成單一商品的蝦皮上架文案。

    Args:
        product_data: extract_1688.js 抓的 JSON（含 attributes/sku_images/sizes/price_cny）
        sheet_ctx: {"code","selling_price","demand","category"}
        shop: 賣場 key（nail/lady/baby）→ 決定品牌標籤/SOP/尺碼規則（scraper/shops.py）

    Returns:
        dict（上面 JSON 結構）；失敗時 flags 帶錯誤、其餘空。
    """
    import anthropic

    from scraper.shops import get_shop

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("缺少 ANTHROPIC_API_KEY")
        return {"error": "no_api_key", "flags": ["缺少 ANTHROPIC_API_KEY"]}

    sp = get_shop(shop)
    system_text = _build_system(sp)

    colors = list(product_data.get("sku_images", {}).keys()) or \
        [s.get("attributes", {}).get("规格", "") for s in product_data.get("skus", [])]
    task = _TASK.format(
        subcategory_line=sp.subcategory_line,
        title_rule=_title_rule(sp),
        size_rule=sp.size_rule,
        code=sheet_ctx.get("code", ""),
        price=sheet_ctx.get("selling_price", ""),
        demand=sheet_ctx.get("demand", ""),
        category=sheet_ctx.get("category", "") or "（未指定，依商品判斷）",
        style_note=sheet_ctx.get("style_note", "") or "全款式（全部保留）",
        title=product_data.get("title", ""),
        attributes=json.dumps(product_data.get("attributes", {}), ensure_ascii=False),
        colors="、".join(colors),
        sizes="、".join(product_data.get("sizes", [])) or "（無尺碼軸）",
        price_cny=product_data.get("price_cny", 0),
    )

    client = anthropic.Anthropic(api_key=api_key)
    logger.info(f"[{sheet_ctx.get('code')}] Claude 生成文案中…")
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=[{"type": "text", "text": system_text,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": task}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        if result.get("description"):
            result["description"] = scrub_jin(result["description"])
        logger.info(f"[{sheet_ctx.get('code')}] 標題：{result.get('title','')[:40]}")
        if result.get("flags"):
            for fl in result["flags"]:
                logger.warning(f"[{sheet_ctx.get('code')}] flag: {fl}")
        return result
    except json.JSONDecodeError:
        logger.error("Claude 回傳非 JSON")
        return {"error": "bad_json", "raw": text[:500], "flags": ["回傳非 JSON"]}
    except Exception as e:
        logger.error(f"Claude API 錯誤：{e}")
        return {"error": str(e), "flags": [f"API 錯誤：{e}"]}


def scrub_jin(text: str) -> str:
    """把文案內文的體重「斤」統一成公斤：斤‧kg 並列→只留 kg；單獨斤範圍→÷2 換算。"""
    import re
    # 「80-100斤 ‧ 約40-50 kg」→「40-50 kg」
    text = re.sub(r"[\d.]+\s*[-–~]\s*[\d.]+\s*斤\s*[‧·/、,，]?\s*約?\s*([\d.]+\s*[-–~]\s*[\d.]+\s*kg)",
                  r"\1", text)
    # 單獨「80-95 斤」→「40-47.5 kg」

    def _c(m):
        return f"{float(m.group(1)) / 2:g}-{float(m.group(2)) / 2:g} kg"
    text = re.sub(r"([\d.]+)\s*[-–~]\s*([\d.]+)\s*斤", _c, text)
    return text


def _clean_size_key(s: str) -> str:
    """尺碼 key 只留字母/數字（S/M/L/XL/2XL…），砍掉【…】(…)（…）斤 等體重括號（供貨號用）。"""
    import re
    k = re.split(r"[（(【\[]", str(s))[0].strip()
    return k or str(s).strip()


def _label_kg(label: str, size: str) -> str:
    """尺碼選項標籤體重統一成公斤：優先抽 kg 範圍；沒 kg 就斤÷2；都沒有則砍斤字殘留。"""
    import re
    m = re.search(r"([\d.]+)\s*[-–~]\s*([\d.]+)\s*kg", str(label))
    if m:
        return f"{size}（{m.group(1)}-{m.group(2)}kg）"
    m2 = re.search(r"([\d.]+)\s*[-–~]\s*([\d.]+)\s*斤", str(label))
    if m2:
        return f"{size}（{float(m2.group(1)) / 2:g}-{float(m2.group(2)) / 2:g}kg）"
    return re.sub(r"\s*[【\[]?[\d.]*[-–~]?[\d.]*\s*斤[^）)】\]]*[】\]]?", "", str(label)).strip()


def build_variants(code: str, short_name: str, color_map: dict,
                   selected_colors: list[str], size_labels: dict,
                   selected_sizes: list[str]) -> dict:
    """用程式拼蝦皮二階規格（確保精準，不交給 LLM）。各司其職：

    - 規格選項1（買家看，I 欄）：`簡稱_繁體顏色`（不含編號；蝦皮限 ≤20 字，故砍編號）
    - 規格選項2（買家看，L 欄）：size_labels[尺碼]（尺碼 + 廠商數據）
    - `color` / `size`：純顏色 / 純尺碼，供 shopee_excel 拼「商品選項貨號」= 編號_顏色_尺碼

    每個 tier1 帶 color（供貨號），tier2 帶 size（供貨號）。
    """
    tier1 = []
    for c in selected_colors:
        zh = color_map.get(c, c)
        buyer = f"{short_name}_{zh}" if short_name else zh
        tier1.append({"src_1688": c, "color": zh, "option_name": buyer})
    tier2 = []
    for s in selected_sizes:
        key = _clean_size_key(s)
        tier2.append({"size": key, "option_name": _label_kg(size_labels.get(s, s), key)})
    return {"規格1_顏色": tier1, "規格2_尺碼": tier2,
            "sku_count": len(tier1) * len(tier2)}
