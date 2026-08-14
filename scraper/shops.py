"""三賣場（Nail / Lady / Baby）上架設定的單一正本。

上架 pipeline 原本是 Lady 單賣場版，賣場相關的假設散在各模組
（名單 Sheet、分類對照、文案 prompt、顏色政策、模板、物流、cookie）。
三賣場化後全部收斂到這裡：每個賣場一個 ShopProfile，其他模組帶 shop 參數查表。

⚠️ 人工需準備的 per-shop 外部件（缺件時會明確報錯，不會靜默用錯賣場的）：
1. 蝦皮模板：各賣場後台下載「批次上傳基礎模板」→ 存 config/shopee_template_{shop}.xlsx。
   模板第 2 列藏版本 hash + 物流欄位組合是賣場設定 → 絕不可跨賣場共用一份。
   （lady 暫時 fallback 到舊路徑 config/shopee_template.xlsx，向後相容。）
2. AI 上架名單：各賣場一張 Google Sheet（分享給 inventory-sync SA），
   ID 填 .env 的 AI_LIST_SHEET_ID_<SHOP>（gid 用 AI_LIST_SHEET_GID_<SHOP>，預設 0）。
3. 1688 cookie：cookie-hub 警衛室 refresh 1688_{shop}（標準庫 ~/.joyslu/cookies/）。

標題/分類/選項政策的「依據」（含哪些是草案待 Edwin 確認）見 docs/三賣場上架依據.md。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SHOP_KEYS = ("nail", "lady", "baby")


@dataclass(frozen=True)
class ShopProfile:
    key: str                      # nail / lady / baby
    brand_tag: str                # 標題開頭的品牌標籤，如【JoysLu Lady】
    shop_desc: str                # 文案 prompt 的賣場自介（角色設定用）
    audience_word: str            # 標題必含的受眾/類別詞（lady=女裝）
    cookie_hub_key: str           # cookie-hub 警衛室的帳號 key（refresh 用）
    axis1_name: str               # 蝦皮規格名稱 1（每列都填）
    axis2_name: str               # 蝦皮規格名稱 2（有第二軸才填）
    category_map: dict[str, str]  # 名單「分類」欄文字 → 蝦皮分類 ID
    name_rules: list[tuple[list[str], str]]  # 商品名關鍵詞 → 分類 ID（由具體到籠統）
    sop_files: list[str]          # 文案 SOP（相對 config/sop/；全文塞進 system prompt）
    color_policy: str             # "clothing"=女裝中性色政策 / "cap_only"=只守 SKU 上限不砍色
    max_base_colors: int          # clothing 政策的底色上限
    sku_cap: int = 100            # 蝦皮單商品 SKU 上限
    enabled_channels: frozenset[str] = frozenset()   # 物流頻道（channel_id）
    channels_confirmed: bool = False  # False=沿用 Lady 的組合當草案，待 Edwin 確認
    title_extra: str = ""         # 標題規則的補充說明（塞進 prompt）
    size_rule: str = ""           # 尺碼/第二軸的 prompt 規則（服飾才有斤→kg）
    subcategory_line: str = ""    # 「判子品類」的選項說明

    # ── 衍生路徑（統一從這裡拿，不要各模組自己拼）──────────────
    @property
    def csv_path(self) -> Path:
        return BASE_DIR / "input" / f"{self.key}_ai_list.csv"

    @property
    def cookie_path(self) -> Path:
        return Path.home() / ".joyslu" / "cookies" / f"1688_{self.key}.json"

    @property
    def excel_name(self) -> str:
        return f"shopee_batch_upload_{self.key}.xlsx"

    def template_path(self) -> Path:
        """該賣場的蝦皮模板。缺件時報清楚的中文錯誤（絕不退到別賣場的模板）。"""
        p = BASE_DIR / "config" / f"shopee_template_{self.key}.xlsx"
        if p.exists():
            return p
        if self.key == "lady":
            legacy = BASE_DIR / "config" / "shopee_template.xlsx"
            if legacy.exists():
                return legacy
        raise FileNotFoundError(
            f"缺【{self.key}】的蝦皮模板：請到該賣場的蝦皮後台下載「批次上傳基礎模板」，"
            f"存成 {p}（模板藏版本 hash 且物流欄位是賣場設定，不可拿別賣場的用）")

    def ai_list_sheet(self) -> tuple[str, str]:
        """該賣場的 AI 上架名單 (sheet_id, gid)。未設定時報清楚的中文錯誤。"""
        from config.settings import AI_LIST_SHEETS
        cfg = AI_LIST_SHEETS.get(self.key) or {}
        if not cfg.get("id"):
            raise RuntimeError(
                f"【{self.key}】AI 上架名單尚未設定：請建立該賣場的名單表（欄位比照 Lady：編號/"
                f"進貨網址/分類/款式/尺寸/售價/訂貨需求）、分享給 inventory-sync SA，"
                f"再到 .env 設 AI_LIST_SHEET_ID_{self.key.upper()}=<sheet_id>"
                f"（分頁非第一頁時另設 AI_LIST_SHEET_GID_{self.key.upper()}）")
        return cfg["id"], str(cfg.get("gid") or "0")

    def sop_texts(self) -> list[tuple[str, str]]:
        """[(檔名, 全文)]。SOP 檔缺失時明確報錯（文案規範是過審依據，不可靜默略過）。"""
        out = []
        for rel in self.sop_files:
            p = BASE_DIR / "config" / "sop" / rel
            if not p.exists():
                raise FileNotFoundError(f"缺文案 SOP：{p}（{self.key} 賣場的文案規範）")
            out.append((p.name, p.read_text(encoding="utf-8")))
        return out


# ★物流公版（Edwin 2026-08-15 定案）：三賣場一律用這 6 個，各賣場後台多開通的物流一概不理。
# 新竹物流 30020 / 全家 30006 / 7-ELEVEN 30005 / 店到家宅配 30017 / 蝦皮店到店 30015 / 嘉里快遞 30018
# （模板沒該頻道欄位的會自動略過不填，所以跨賣場安全；預購品不開店到店隔日到貨。）
_STD_CHANNELS = frozenset({"30020", "30006", "30005", "30017", "30015", "30018"})
_LADY_CHANNELS = _STD_CHANNELS  # 舊名保留（Lady 註解沿用）

# ══════════════════════════════════════════════════════════════
# Lady（女裝）— 現行正線，行為與單賣場版完全一致
# ══════════════════════════════════════════════════════════════
_LADY = ShopProfile(
    key="lady",
    brand_tag="【JoysLu Lady】",
    shop_desc="JoysLu Lady 蝦皮（台灣站）女裝賣場",
    audience_word="女裝",
    cookie_hub_key="1688_lady",
    axis1_name="顏色",
    axis2_name="尺碼",
    category_map={
        "長褲": "100358", "褲子": "100358", "闊腿褲": "100358", "寬褲": "100358",
        "牛仔褲": "100103",
        "短褲": "100360",
        "褲裙": "100361",
        "裙裝": "100102", "半身裙": "100102", "裙子": "100102",
        "T恤": "100352", "短袖": "100352",
        "上衣": "100356",
        "襯衫": "100353",
    },
    name_rules=[
        (["裙裤", "裙褲", "褲裙", "裤裙"], "100361"),
        (["牛仔"], "100103"),
        (["半身裙", "花苞裙", "伞裙", "傘裙", "碎花裙", "a字裙", "连衣裙",
          "連衣裙", "长裙", "長裙", "短裙", "裙"], "100102"),
        (["短裤", "短褲", "五分裤", "五分褲"], "100360"),
        (["阔腿", "闊腿", "西装裤", "西裝褲", "工装", "工裝", "运动裤",
          "運動褲", "山本", "弯刀", "彎刀", "喇叭", "直筒", "哈伦", "哈倫",
          "西裤", "西褲", "长裤", "長褲", "裤", "褲"], "100358"),
        (["t恤", "短袖", "上衣", "衬衫", "襯衫", "polo"], "100352"),
    ],
    sop_files=["03f_女裝通用SOP_v1.0.md", "JoysLu_Lady_詳情頁規範_系統化版_v2.4.md"],
    color_policy="clothing",
    max_base_colors=5,
    enabled_channels=_LADY_CHANNELS,
    channels_confirmed=True,
    title_extra="",
    size_rule=(
        "6. 尺碼標籤：每個尺碼配廠商有給的數據（體重/身高/三圍）；廠商沒給就只放尺碼字母，不硬湊。\n"
        "   ★體重單位一律用「公斤(kg)」：廠商標「斤」時務必 ÷2 換算（1斤=0.5kg，如 80-95斤→40-47.5kg）。\n"
        "   標籤只寫 kg、**絕對不可出現「斤」字**，也不要「斤 ‧ kg」並列。格式範例：「S（40-47.5kg）」"),
    subcategory_line="上衣/外套/下身/裙裝/連身類",
)

# ══════════════════════════════════════════════════════════════
# Nail（美甲）— 草案：分類 ID 取自模板分類表（真實 ID），細節待實跑校準
# ══════════════════════════════════════════════════════════════
_NAIL = ShopProfile(
    key="nail",
    brand_tag="【JoysLu Nail】",
    shop_desc="JoysLu Nail 蝦皮（台灣站）美甲材料賣場（客群：美甲師與美甲愛好者）",
    audience_word="美甲",
    cookie_hub_key="1688_nail",
    axis1_name="顏色",
    axis2_name="規格",
    category_map={
        "甲油膠": "102178", "凝膠": "102178", "美甲凝膠": "102178",
        "指甲油": "102029",
        "美甲工具": "102031", "工具": "102031",
        "工具材料": "102034", "美甲材料": "102034", "飾品": "102034", "鑽飾": "102034",
        "美甲片": "102032", "甲片": "102032",
        "貼紙": "102033", "指甲貼紙": "102033", "貼膜": "102033",
        "卸甲": "102030",
        "基底油": "101615", "護色油": "101615", "營養油": "101615",
        "其他": "102035",
    },
    name_rules=[
        (["甲油胶", "甲油膠", "光疗胶", "光療膠", "延长胶", "延長膠", "封层", "封層",
          "底胶", "底膠", "加固胶", "加固膠", "功能胶", "功能膠", "彩胶", "彩膠",
          "猫眼", "貓眼"], "102178"),                                   # 美甲凝膠
        (["贴纸", "貼紙", "贴花", "貼花", "水贴", "水貼"], "102033"),     # 指甲貼紙
        (["甲片", "穿戴甲"], "102032"),                                  # 美甲片
        (["卸甲", "洗甲"], "102030"),                                    # 卸甲工具
        (["光疗灯", "光療燈", "美甲灯", "美甲燈", "打磨机", "打磨機",
          "笔", "筆", "剪", "钳", "鉗", "锉", "銼"], "102031"),          # 美甲工具
        (["钻", "鑽", "饰品", "飾品", "配件", "铆钉", "鉚釘", "金属", "金屬"], "102034"),
        (["营养油", "營養油", "底油", "护色", "護色"], "101615"),
        (["美甲", "指甲"], "102035"),                                    # 兜底：指甲保養/其他
    ],
    sop_files=["nail/JoysLu_Nail_上架SOP_草案v0.md"],
    color_policy="cap_only",       # 美甲色號是商品本體，不套女裝砍色政策；只守 100 SKU
    max_base_colors=0,             # cap_only 不用
    enabled_channels=_STD_CHANNELS,    # 公版 6 個（Edwin 2026-08-15 定案，三賣場一律）
    channels_confirmed=True,
    title_extra="美甲商品常以色號/型號為賣點，標題點出質地與用途（如 光療 甲油膠 貓眼）。",
    size_rule=(
        "6. 規格標籤：第二軸若是容量/型號/尺寸（如 8ml/15ml、圓頭/平頭），原樣繁體化即可，"
        "不要腦補數據；沒有第二軸就回空物件 {}。"),
    subcategory_line="甲油膠/貼紙/甲片/工具/飾品/保養/其他",
)

# ══════════════════════════════════════════════════════════════
# Baby（母嬰）— 草案：對齊 #S160 重啟定案（孕婦四品項為核心 + 嬰幼用品）
# ══════════════════════════════════════════════════════════════
_BABY = ShopProfile(
    key="baby",
    brand_tag="【JoysLu Baby】",
    shop_desc="JoysLu Baby 蝦皮（台灣站）母嬰用品賣場（客群：孕媽咪與嬰幼兒家長）",
    audience_word="",              # 母嬰品類詞多元（孕婦/嬰兒/寶寶），不強制單一詞，由分類帶
    cookie_hub_key="1688_baby",
    axis1_name="顏色",
    axis2_name="尺碼",
    category_map={
        # 孕婦四品項（#S160 重啟核心）
        "孕哺內衣": "100393", "哺乳內衣": "100393",
        "哺乳衣": "100396",
        "孕婦褲": "100398", "孕婦下著": "100398",
        "月子服": "100396",        # 月子服掛哺乳衣（女生衣著/孕婦裝/哺乳衣）
        "孕婦洋裝": "100394", "孕婦上衣": "100395", "孕婦套裝": "100397",
        "托腹帶": "100961",
        "孕婦用品": "100963",
        # 嬰幼
        "包屁衣": "101022", "連身裝": "101022",
        "嬰幼上衣": "101021", "嬰幼褲": "101740", "嬰幼洋裝": "101018",
        "嬰幼套裝": "101023", "居家服": "101020",
        "圍兜": "100957", "口水巾": "100957",
    },
    name_rules=[
        (["哺乳内衣", "哺乳內衣", "孕妇内衣", "孕婦內衣", "哺乳文胸"], "100393"),
        (["月子服", "哺乳衣", "哺乳裙", "喂奶", "餵奶"], "100396"),
        (["孕妇裤", "孕婦褲", "托腹裤", "托腹褲", "孕妇打底", "孕婦打底"], "100398"),
        (["孕妇连衣裙", "孕婦洋裝", "孕妇裙", "孕婦裙"], "100394"),
        (["托腹带", "托腹帶", "束腹"], "100961"),
        (["孕妇", "孕婦", "孕期"], "100963"),                            # 孕婦兜底
        (["包屁衣", "连体衣", "連體衣", "爬服", "哈衣"], "101022"),
        (["围兜", "圍兜", "口水巾"], "100957"),
        (["婴儿裤", "嬰兒褲", "宝宝裤", "寶寶褲"], "101740"),
        (["婴儿", "嬰兒", "宝宝", "寶寶", "新生儿", "新生兒"], "101025"),  # 嬰幼兒裝/其他 兜底
    ],
    sop_files=["baby/JoysLu_Baby_上架SOP_草案v0.md"],
    color_policy="cap_only",       # 母嬰花色（印花/圖案）是賣點，不套女裝中性色砍法；只守 100 SKU
    max_base_colors=0,
    enabled_channels=_STD_CHANNELS,    # 公版 6 個（Edwin 2026-08-15 定案，三賣場一律）
    channels_confirmed=True,
    title_extra="孕婦品項標題點出孕期適用場景（孕哺/產後/月子）；嬰幼品項點出月齡/材質安全。",
    size_rule=(
        "6. 尺碼標籤：孕婦服飾比照女裝——體重一律「公斤(kg)」，廠商標「斤」÷2 換算、"
        "絕不可出現「斤」字（如 80-95斤→40-47.5kg）；嬰幼服飾用身高/月齡（如 73cm（6-12月））；"
        "廠商沒給數據就只放尺碼字，不硬湊。"),
    subcategory_line="孕哺內衣/哺乳衣/孕婦褲/月子服/嬰幼兒裝/哺育用品/其他",
)

SHOPS: dict[str, ShopProfile] = {"nail": _NAIL, "lady": _LADY, "baby": _BABY}


def get_shop(key: str | None) -> ShopProfile:
    k = (key or "lady").strip().lower()
    if k not in SHOPS:
        raise KeyError(f"未知賣場 {key!r}，可用：{', '.join(SHOPS)}")
    return SHOPS[k]
