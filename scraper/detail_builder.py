"""詳情組裝（Nail，2026-09-17 Edwin 定版「中間版本」）。

程式搭框架、只填有把握的，其餘交給人在待上架區補：
  1. 商品特色   ← AI（只依標題與屬性表，不誇大）
  2. 商品規格   ← AI（只列屬性表有的；沒有就整段不寫，**不放「待補」**——漏補就被買家看到）
  3. 使用方法   ← AI（依品類的通用步驟）
  4. 款式說明   ← 程式（直接列這次上架的選項名稱，不解釋差異——差異要肉眼看）
  5. 注意事項   ← 固定文案（依品類寫死，每支一致，不讓 AI 每次重寫）
拿掉：賣場介紹（寫過「提供現貨」、預購品會錯）、退換貨（蝦皮後台已統一）、
推薦搭配（AI 會編出賣場沒有的商品，9/9 HNV1 寫了「防塵口罩／防塵墊」）。

為什麼不讓 AI 讀詳情圖：1688 一頁常掛十幾款，我們只進其中兩款，圖剛好是別款的機率很高，
規則寫不完、特例太多 → 交給人看（Edwin 2026-09-17）。
"""
from __future__ import annotations

import re

# 版號在 scraper/shops.py 的 detail_version：改了組裝規則就換版號 → 舊文案快取自動作廢重生

# ── 注意事項固定文案（依品類）──────────────────────────────────
NOTICE = {
    "光療": [
        "請避免直接接觸皮膚，沾到時請立即擦拭清潔",
        "皮膚敏感者使用前請先小範圍測試",
        "孕婦、哺乳期間請先諮詢專業意見再使用",
        "請避光、密封存放於陰涼處，並放在孩童拿不到的地方",
    ],
    "電器": [
        "使用前請確認電壓與插頭規格與所選款式相符",
        "清潔或更換配件前請先關機並拔除電源",
        "請勿碰水或在潮濕環境使用，請勿自行拆解機身",
        "請放在孩童拿不到的地方",
    ],
    "工具耗材": [
        "購買前請確認尺寸、型號是否符合您的需求或機型",
        "使用後請清潔並保持乾燥",
        "尖銳或細小物品請放在孩童拿不到的地方",
    ],
}

_GEL_CATEGORIES = {"102178", "102029"}            # 美甲凝膠、指甲油
_GEL_WORDS = ("膠", "胶", "甲油", "封層", "封层")
_ELECTRIC_WORDS = ("燈", "灯", "打磨機", "打磨机", "磨甲機", "磨甲机", "磨甲筆", "磨甲笔",
                   "吸塵器", "吸尘器", "集塵器", "集尘器", "粉塵機", "粉尘机", "電動", "电动",
                   "充電", "充电", "蓄電", "蓄电", "USB")
_PART_WORDS = ("濾網", "滤网", "濾紙", "过滤纸", "過濾", "过滤", "濾棉", "滤棉", "收納", "收纳")


def notice_kind(category: str, *names: str) -> str:
    """品類 → 注意事項用哪一套。耗材配件（濾網/濾紙）即使名稱含「吸塵器」也歸工具耗材。"""
    if str(category) in _GEL_CATEGORIES:
        return "光療"
    # 先看我們自己的品名（最準），認不出才看 1688 標題——1688 標題描述的是整頁，
    # 濾紙那列的頁面標題寫的是「吸塵器」，機器頁的標題也可能順帶寫「過濾網」
    for text in names:
        if not text:
            continue
        if any(w in text for w in _GEL_WORDS):
            return "光療"
        if any(w in text for w in _PART_WORDS):
            return "工具耗材"
        if any(w in text for w in _ELECTRIC_WORDS):
            return "電器"
    return "工具耗材"


def _strip_ai_extra(ai_desc: str) -> str:
    """AI 偶爾還是會多寫款式/注意事項/賣場介紹 → 從那個標題起全部切掉（程式另外組）。"""
    cut = re.search(r"^\s*✦?\s*(顏色|款式|注意事項|賣場介紹|退換貨|推薦搭配)", ai_desc or "", re.M)
    return (ai_desc[:cut.start()] if cut else (ai_desc or "")).strip()


def assemble_description(ai_desc: str, variants: dict, category: str,
                         short_name: str = "", title_1688: str = "") -> str:
    """AI 三段 ＋ 程式款式說明 ＋ 固定注意事項 → 蝦皮詳情全文。"""
    parts = [_strip_ai_extra(ai_desc)]

    t1 = [c.get("option_name") or c.get("color", "") for c in variants.get("規格1_顏色", [])]
    t2 = [s.get("option_name") or s.get("size", "") for s in variants.get("規格2_尺碼", [])]
    lines = [f"・{o}" for o in t1 if o]
    if t2:
        lines.append("可選規格：" + "／".join(o for o in t2 if o))
    if lines:
        parts.append("✦ 款式說明\n" + "\n".join(lines))

    kind = notice_kind(category, short_name, title_1688)
    parts.append("✦ 注意事項\n" + "\n".join(f"・{x}" for x in NOTICE[kind]))
    return "\n\n".join(p for p in parts if p)
