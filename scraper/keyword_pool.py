"""搜尋詞庫讀取器（2026-09-16 建，Nail 先行）。

Edwin 逐字去蝦皮廣告後台查回來的搜尋量（321 個詞），存在
「【Nail】搜尋詞庫」Google Sheet。這裡把它讀成「這支商品可以用哪些詞」，
給文案引擎組標題尾串、並把可用詞清單交給 AI。

## 為什麼要有這支

標題的尾串原本寫死在 SOP 裡（`美甲 美甲燈 光療燈 美甲工具 …`）。寫死有兩個問題：
① 搜尋量會變，改一次要動規範；② 新品類（集塵器、打磨機）就得再寫一套。
改成讀表之後，Edwin 更新數字、尾串自動跟著變，不必改程式也不必改規範。

## 三條紀律（都是實際資料逼出來的）

⚠️ **量大不等於能用**：`過濾棉 11622`（魚缸／空氣清淨機）、`分裝瓶 48203`（化妝品）、
`打磨機 8184`（木工五金）——搜這些字的人多半不是要買美甲用品，把他們引進來只會
**拉低點擊率與轉換**，廣告還要付錢。表上以 `相關性` 欄標記，這裡只取「美甲」。

⚠️ **品牌詞不可進標題**：`莎夏美甲美學用品 7366`、`愛美佳美甲 2269` 這類競品／他牌詞，
拿去投廣告是常規操作，寫進自己的標題是侵權與不實標示。本模組一律排除 `位階=品牌`。

⚠️ **死詞留著不刪**：`烘甲燈 5`、`光撩燈 0` 留在表上標成死詞——刪掉三個月後會有人再查一次。
這裡靠 `狀態=啟用` 過濾，不靠「表上有沒有這個詞」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from loguru import logger

SHEET_ID = "1lCZ-NP63EyvhKy9RK_KEkBSJrCQIaxvjelFXZCLqjBY"   # 【Nail】搜尋詞庫
# 分頁名會被改（原本叫「詞池」，2026-09-16 改成「搜尋詞庫」）→ 給候選，
# 都找不到才退回第一個分頁並**喊一聲**：靜默回空會讓標題默默退回沒有關鍵字的版本。
TAB_CANDIDATES = ("搜尋詞庫", "詞池", "關鍵字", "keywords")

# 商品 → 搜尋詞庫分類。用品名關鍵詞判，由具體到籠統，第一個命中就用。
# ⚠️ 不用蝦皮分類 ID：那是給蝦皮看的（美甲工具底下同時有集塵器、打磨機、收納盒），
#    分不出「這支該用哪一池的詞」。
CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    # ⚠️ 繁簡都要列：品名是我們寫的繁體，1688 原標題是簡體，兩邊都會拿來認
    #    （實測「SUN3 48W 智能二代」品名裡沒有「燈」字，只有 1688 標題的「美甲灯」認得出來）
    (("集塵", "吸塵", "粉塵", "濾網", "過濾", "濾紙", "濾棉",
      "集尘", "吸尘", "粉尘", "滤网", "过滤", "滤纸", "滤棉"), "集塵器"),
    (("打磨", "磨甲", "磨頭", "拋光", "卸甲機", "磨头", "抛光", "卸甲机"), "打磨機"),
    (("光療燈", "美甲燈", "烤燈", "一字燈", "手持燈", "燈",
      "光疗灯", "美甲灯", "烤灯", "灯"), "美甲燈"),
    (("收納", "工具箱", "推車", "收纳", "推车"), "收納"),
    (("貓眼",), "貓眼"),
    (("甲片", "穿戴"), "甲片"),
    (("膠", "封層", "底膠"), "膠"),
    (("筆刷", "彩繪筆", "拉線筆"), "美甲筆"),
    (("卸甲水", "清潔液", "洗筆"), "溶劑"),
]


@dataclass
class Word:
    詞: str
    量: int
    分類: str
    位階: str


@dataclass
class Pool:
    """某一支商品可用的詞：該分類 ＋ 廣域，量降冪。"""

    分類: str
    words: list[Word] = field(default_factory=list)

    def top(self, n: int = 12) -> list[str]:
        return [w.詞 for w in self.words[:n]]

    def tail(self, budget: int) -> str:
        """組標題尾串：依量降冪塞到 budget 個字為止（半形空格分隔）。"""
        out: list[str] = []
        used = 0
        for w in self.words:
            cost = len(w.詞) + (1 if out else 0)
            if used + cost > budget:
                continue
            out.append(w.詞)
            used += cost
        return " ".join(out)


def category_of(product_name: str, extra: str = "", fallback: str = "") -> str:
    """從品名（＋1688 原標題）推搜尋詞庫分類；推不出回 fallback。

    先看品名、再看 1688 標題：品名是 Edwin 寫的、比較準；1688 標題是備援，
    但它描述的是**整頁最強那款**，所以只在品名認不出來時才用。
    """
    for text in (product_name or "", extra or ""):
        for keys, cat in CATEGORY_RULES:
            if any(k in text for k in keys):
                return cat
    return fallback


@lru_cache(maxsize=1)
def _load() -> list[Word]:
    """讀整張搜尋詞庫（只取能用的：美甲相關、啟用、非品牌）。"""
    import gspread
    from google.oauth2.service_account import Credentials

    from scraper.master_reader import resolve_sa_json

    creds = Credentials.from_service_account_file(
        str(resolve_sa_json(None)), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(SHEET_ID)
    titles = [w.title for w in sh.worksheets()]
    tab = next((t for t in TAB_CANDIDATES if t in titles), None)
    if tab is None:
        tab = titles[0]
        logger.warning(f"搜尋詞庫找不到 {TAB_CANDIDATES} 任一分頁，改用第一個分頁「{tab}」")
    rows = sh.worksheet(tab).get_all_values()
    if not rows:
        return []
    h = {name: i for i, name in enumerate(rows[0])}
    need = ("詞", "搜尋量", "分類", "位階", "相關性", "狀態")
    missing = [c for c in need if c not in h]
    if missing:
        # 欄位被改名就講出來——靜默回空會讓標題默默退回沒有關鍵字的版本
        logger.warning(f"搜尋詞庫缺欄位 {missing}，本次不套用搜尋詞庫")
        return []
    out: list[Word] = []
    for r in rows[1:]:
        if len(r) <= max(h.values()) or not r[h["詞"]].strip():
            continue
        if r[h["狀態"]].strip() != "啟用":
            continue
        if r[h["相關性"]].strip() != "美甲":
            continue
        if r[h["位階"]].strip() == "品牌":        # 競品／他牌字：可投廣告，不可進標題
            continue
        try:
            vol = int(str(r[h["搜尋量"]]).replace(",", "").strip())
        except ValueError:
            continue
        out.append(Word(r[h["詞"]].strip(), vol, r[h["分類"]].strip(), r[h["位階"]].strip()))
    out.sort(key=lambda w: -w.量)
    logger.info(f"搜尋詞庫載入 {len(out)} 個可用詞（已排除泛用／品牌／死詞）")
    return out


def pool_for(product_name: str, category: str = "", extra: str = "") -> Pool:
    """這支商品可用的搜尋詞庫＝該分類 ＋ 廣域（量降冪、去重）。"""
    cat = category or category_of(product_name, extra)
    seen: set[str] = set()
    words: list[Word] = []
    for w in _load():
        cats = {c.strip() for c in w.分類.split(",") if c.strip()}
        if cat not in cats and "廣域" not in cats:
            continue
        if w.詞 in seen:
            continue
        seen.add(w.詞)
        words.append(w)
    return Pool(cat, words)


def prompt_block(product_name: str, category: str = "", extra: str = "",
                 n: int = 16, budget: int = 40) -> str:
    """給文案 prompt 用的一段：可用詞清單＋建議尾串。

    ⚠️ 只給「可以用的詞」，不解釋為什麼別的不能用——prompt 越短模型越照做。
    """
    p = pool_for(product_name, category, extra)
    if not p.words:
        return ""
    lines = [f"【可用關鍵字（{p.分類 or '廣域'}，依蝦皮實際搜尋量降冪）】"]
    lines += [f"　{w.詞}（{w.量}）" for w in p.words[:n]]
    lines.append(f"【建議尾串】{p.tail(budget)}")
    lines.append("只能用上面列出的詞；沒列的詞代表沒有搜尋量或不是美甲客群，不要自己發明。")
    lines.append("⚠️ 標題要**填到 58-60 字**——60 字是免費版位，少一個字就少一次被搜到的機會。"
                 "數過字數若不足 58，從清單往下再補詞。")
    return "\n".join(lines)


_SPEC_RE = re.compile(r"\d+\s*(?:W|w|瓦|V|v|伏|ml|ML|毫升|g|G|克|顆|珠|轉|rpm|RPM|片|入|吋|cm|CM)")


def unverified_specs(title: str, sources: list[str]) -> list[str]:
    """標題裡出現、但在來源資料找不到的規格詞。

    Edwin 2026-09-15 的疑慮：一個 1688 網址底下常有好幾款（實測 `760973597185` 同頁有
    「302吸塵打磨機二合一 / G1S渦輪美甲吸塵器 / 吸塵器濾網」三種不同商品），而頁面標題
    描述的是最強那款 → AI 很可能把 A 款的瓦數寫進 C 款的標題，那是**不實標示**不是文案問題。
    規範寫「規格只能來自已驗證資料」擋不住模型，所以再加一道機器檢查。
    """
    hay = " ".join(s or "" for s in sources)
    hay_norm = re.sub(r"\s+", "", hay).lower()
    bad = []
    for m in _SPEC_RE.finditer(title or ""):
        tok = re.sub(r"\s+", "", m.group()).lower()
        if tok not in hay_norm:
            bad.append(m.group().strip())
    return bad
