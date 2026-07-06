"""
文案引擎：用 Claude + JoysLu Lady SOP 生成蝦皮上架文案。

輸入：extract_1688.js 抓的兩軸商品資料 + 採購表脈絡（編號 / 售價 / 訂貨需求 / 分類）
輸出：商品簡稱 / 蝦皮標題 / 詳情頁 8 區塊 / 繁體顏色對照 / 尺碼標籤 / flags
      （變體選項名稱「編號_簡稱_顏色」由 build_variants() 用程式拼，不交給 LLM 確保精準）

SOP 來源（config/sop/）：
- 03f_女裝通用SOP_v1.0.md     女裝品類規則（A-* 適用）
- JoysLu_Lady_詳情頁規範_系統化版_v2.4.md  母規範（字典/固定文案/8區塊/檢查）

大 SOP 走 Anthropic prompt cache（system 陣列 + cache_control），多商品連跑省 input。
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

SOP_DIR = Path(__file__).parent.parent / "config" / "sop"
MODEL = "claude-sonnet-4-6"

_ROLE = """你是 JoysLu Lady 蝦皮（台灣站）女裝賣場的上架文案專家。
嚴格遵守下方兩份規範產出文案。核心心法：廠商有寫就用、沒寫套 fallback 或省略、
不腦補機能、不過度承諾、抓 80% 完整即可。所有文字一律繁體中文、台灣用語
（不可出現中國用語與簡體字，依字典轉換）。

下面是規範（務必遵守）：

=== 03f 女裝通用 SOP ===
{sop_03f}

=== 母規範 v2.4（字典 / 固定文案 / 8 區塊 / 檢查）===
{sop_v24}
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
1. 判子品類（上衣/外套/下身/裙裝/連身類）
2. 商品簡稱：依商品名濃縮成 2-5 字繁體台灣用語（如「冰丝阔腿裤」→「冰絲寬褲」）
3. 蝦皮標題：依 SOP §11 / 標題規則，含【JoysLu Lady】+ 核心關鍵字 +「女裝」+ 編號，57-60 字寬內
4. 完整詳情頁（通用 8 區塊全文，套母規範固定文案：賣場介紹/退換貨/推薦三款）
5. 顏色簡繁對照：把每個第一軸顏色轉成繁體乾淨名（去掉廠商括號贅字，如「米白色【长裤】」→「米白色」；款式差異若需保留另說）
6. 尺碼標籤：每個尺碼配廠商有給的數據（體重/身高/三圍）；廠商沒給就只放尺碼字母，不硬湊
7. flags：字典待擴充的新顏色/材質詞、廠商備註、疑似違規詞、子品類不確定、尺碼數據缺漏

【只回傳這個 JSON，不要任何其他文字】
{{
  "subcategory": "子品類",
  "product_short_name": "商品簡稱（繁體）",
  "title": "蝦皮標題",
  "description": "完整 8 區塊詳情頁文案（含換行）",
  "style_kept": ["依款式備註保留的第一軸原始選項名（簡體照原文）"],
  "color_map": {{"1688簡體顏色": "繁體乾淨顏色"}},
  "size_labels": {{"尺碼": "尺碼+數據或純尺碼"}},
  "flags": ["..."]
}}"""


def _load_sop() -> tuple[str, str]:
    f03f = SOP_DIR / "03f_女裝通用SOP_v1.0.md"
    fv24 = SOP_DIR / "JoysLu_Lady_詳情頁規範_系統化版_v2.4.md"
    return f03f.read_text(encoding="utf-8"), fv24.read_text(encoding="utf-8")


def generate_listing(product_data: dict, sheet_ctx: dict) -> dict:
    """
    生成單一商品的蝦皮上架文案。

    Args:
        product_data: extract_1688.js 抓的 JSON（含 attributes/sku_images/sizes/price_cny）
        sheet_ctx: {"code","selling_price","demand","category"}

    Returns:
        dict（上面 JSON 結構）；失敗時 flags 帶錯誤、其餘空。
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("缺少 ANTHROPIC_API_KEY")
        return {"error": "no_api_key", "flags": ["缺少 ANTHROPIC_API_KEY"]}

    sop_03f, sop_v24 = _load_sop()
    system_text = _ROLE.format(sop_03f=sop_03f, sop_v24=sop_v24)

    colors = list(product_data.get("sku_images", {}).keys()) or \
        [s.get("attributes", {}).get("规格", "") for s in product_data.get("skus", [])]
    task = _TASK.format(
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


def build_variants(code: str, short_name: str, color_map: dict,
                   selected_colors: list[str], size_labels: dict,
                   selected_sizes: list[str]) -> dict:
    """用程式拼蝦皮二階規格選項名稱（確保精準，不交給 LLM）。

    規格1（顏色）：編號_簡稱_繁體顏色
    規格2（尺碼）：size_labels[尺碼]（尺碼 + 廠商數據）
    """
    tier1 = []
    for c in selected_colors:
        zh = color_map.get(c, c)
        tier1.append({"src_1688": c, "option_name": f"{code}_{short_name}_{zh}"})
    tier2 = [{"size": s, "option_name": size_labels.get(s, s)} for s in selected_sizes]
    return {"規格1_顏色": tier1, "規格2_尺碼": tier2,
            "sku_count": len(tier1) * len(tier2)}
