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

# 搜尋詞庫「一家一張表」（2026-09-18 起分賣場）：欄位契約相同，但分類體系、相關性值、
# 有沒有「廣域」都不一樣 —— Lady 刻意不設廣域（內褲的標題不該出現絲襪的詞）。
SHEET_ID = "1lCZ-NP63EyvhKy9RK_KEkBSJrCQIaxvjelFXZCLqjBY"   # 【Nail】搜尋詞庫（舊名保留）
LADY_SHEET_ID = "1D7oHF8b5RNICTgckPSR21psr2qkZl4sinrK7RdPSn5w"   # 【Lady】搜尋詞庫（460 詞，9/17 建）
# 分頁名會被改（原本叫「詞池」，2026-09-16 改成「搜尋詞庫」）→ 給候選，
# 都找不到才退回第一個分頁並**喊一聲**：靜默回空會讓標題默默退回沒有關鍵字的版本。
TAB_CANDIDATES = ("搜尋詞庫", "詞池", "關鍵字", "keywords")

# 商品 → 搜尋詞庫分類。用品名關鍵詞判，由具體到籠統，第一個命中就用。
# ⚠️ 不用蝦皮分類 ID：那是給蝦皮看的（美甲工具底下同時有集塵器、打磨機、收納盒），
#    分不出「這支該用哪一池的詞」。
CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    # ⚠️ 繁簡都要列：品名是我們寫的繁體，1688 原標題是簡體，兩邊都會拿來認
    #    （實測「SUN3 48W 智能二代」品名裡沒有「燈」字，只有 1688 標題的「美甲灯」認得出來）
    # ⚠️ 順序＝優先權（2026-09-17 v2.2 重排）：
    #    貓眼**膠**要落「膠」池（貓眼膠 13,644／貓眼指甲油 16,963 在那裡），「貓眼」池是磁鐵／貓眼筆這類配件；
    #    凝膠清潔液、解膠劑含「膠」字但是溶劑 → 溶劑排在膠前面。
    (("集塵", "吸塵", "粉塵", "濾網", "過濾", "濾紙", "濾棉",
      "集尘", "吸尘", "粉尘", "滤网", "过滤", "滤纸", "滤棉"), "集塵器"),
    (("打磨", "磨甲", "磨頭", "拋光", "卸甲機", "磨头", "抛光", "卸甲机"), "打磨機"),
    (("光療燈", "美甲燈", "烤燈", "一字燈", "手持燈", "燈",
      "光疗灯", "美甲灯", "烤灯", "灯"), "美甲燈"),
    (("收納", "工具箱", "推車", "收纳", "推车"), "收納"),
    (("卸甲水", "去光水", "清潔液", "洗筆", "解膠劑", "凝清",
      "卸甲水", "去光水", "清洁液", "洗笔", "解胶剂"), "溶劑"),
    (("卸甲膠", "卸甲包", "卸甲液", "卸甲膏", "卸甲胶"), "卸甲"),
    (("指緣油", "指緣", "護甲", "硬甲油", "養甲", "軟化劑",
      "指缘油", "护甲", "养甲", "软化剂"), "保養"),
    (("膠", "胶", "封層", "封层", "甲油"), "膠"),
    (("貓眼", "猫眼"), "貓眼"),
    (("甲片", "穿戴"), "甲片"),
    (("筆刷", "彩繪筆", "拉線筆", "美甲筆", "笔刷"), "美甲筆"),
]


# Lady：品名 → 搜尋詞庫分類（表上的分類值）。由具體到籠統，第一個命中就用。
LADY_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("bratop", "BraTop", "BRATOP", "背心式內衣", "小可愛"), "BraTop"),
    (("隱形內衣", "隱形胸貼", "nubra", "NuBra", "胸貼"), "隱形內衣"),
    (("胸墊", "襯墊"), "胸墊"),
    (("安全褲",), "安全褲"),
    (("丁字褲", "內褲", "三角褲", "平口褲", "生理褲", "內裤"), "內褲"),
    (("內衣", "胸罩", "бра", "無鋼圈", "有鋼圈", "內衣褲"), "內衣"),
    (("絲襪", "褲襪", "連褲襪", "黑絲", "網襪", "吊帶襪"), "絲襪"),
    (("襪", "襪子", "船襪", "短襪", "中筒", "長筒"), "襪子"),
    (("睡衣", "睡裙", "家居服", "睡袍"), "睡衣"),
    (("泳衣", "泳裝", "比基尼", "泳褲"), "泳衣"),
    (("瑜珈", "運動內衣", "運動褲", "健身"), "運動"),
    (("洋裝", "連身裙", "連衣裙", "连衣裙"), "女裝-洋裝"),
    (("套裝", "两件套", "兩件套"), "女裝-套裝"),
    (("裙",), "女裝-裙"),
    (("褲", "裤"), "女裝-褲"),
    (("上衣", "襯衫", "T恤", "t恤", "背心", "罩衫", "外套", "衛衣", "针织", "針織"), "女裝-上衣"),
    (("髮", "髮飾", "配件", "包包"), "配件"),
]


@dataclass(frozen=True)
class PoolConf:
    """一家賣場的搜尋詞庫設定。欄位契約三家一樣，其餘都不一樣。"""

    sheet_id: str
    relevance: frozenset          # 相關性欄＝「這些值才可以用」
    rules: list                   # 品名 → 分類
    has_broad: bool = False       # 有沒有「廣域」分類（每一類都吃得到）
    pif_categories: frozenset = frozenset()


POOLS = {
    # Nail：相關性只取「美甲」（泛用詞客群不對）、有廣域、化粧品類要 ✅PIF合規
    "nail": PoolConf(SHEET_ID, frozenset({"美甲"}), CATEGORY_RULES, True,
                     frozenset({"膠", "溶劑", "保養"})),
    # Lady：相關性「內著」＝現有商品、「預購」＝女裝與泳衣（自動上架做的正是這種，所以要收）；
    #       位階「錯字」有量但不進標題（品牌詞在 _load_rows 已排除）
    "lady": PoolConf(LADY_SHEET_ID, frozenset({"內著", "預購"}), LADY_CATEGORY_RULES, False),
}


# prompt 裡的例子與客群詞（別讓 Lady 的 prompt 出現貓眼與美甲）
_FORM_EXAMPLES = {"nail": "冰透晶石貓眼、爆裂卸甲膠、手持一字燈",
                  "lady": "冰絲丁字褲、分段壓力長筒襪、莫代爾蕾絲邊三角內褲"}
_AUDIENCE = {"nail": "美甲", "lady": "本賣場"}


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


def category_of(product_name: str, extra: str = "", fallback: str = "", shop: str = "nail") -> str:
    """從品名（＋1688 原標題）推搜尋詞庫分類；推不出回 fallback。

    先看品名、再看 1688 標題：品名是 Edwin 寫的、比較準；1688 標題是備援，
    但它描述的是**整頁最強那款**，所以只在品名認不出來時才用。
    """
    conf = POOLS.get(str(shop).lower())
    rules = conf.rules if conf else CATEGORY_RULES
    for text in (product_name or "", extra or ""):
        for keys, cat in rules:
            if any(k in text for k in keys):
                return cat
    return fallback


@lru_cache(maxsize=4)
def _load_rows(shop: str = "nail") -> tuple[list[Word], list[str]]:
    """讀整張搜尋詞庫 → (可用詞, 不可進標題的詞)。

    不可進標題＝泛用（客群不對）／品牌（他牌）／非啟用（死詞）——標題檢查拿它把混進來的詞挑出來。
    """
    import gspread
    from google.oauth2.service_account import Credentials

    from scraper.master_reader import resolve_sa_json

    creds = Credentials.from_service_account_file(
        str(resolve_sa_json(None)), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    conf = POOLS.get(str(shop).lower())
    if conf is None:
        logger.warning(f"{shop} 還沒有搜尋詞庫 → 標題不套關鍵字清單")
        return [], []
    sh = gspread.authorize(creds).open_by_key(conf.sheet_id)
    titles = [w.title for w in sh.worksheets()]
    tab = next((t for t in TAB_CANDIDATES if t in titles), None)
    if tab is None:
        tab = titles[0]
        logger.warning(f"搜尋詞庫找不到 {TAB_CANDIDATES} 任一分頁，改用第一個分頁「{tab}」")
    rows = sh.worksheet(tab).get_all_values()
    if not rows:
        return [], []
    h = {name: i for i, name in enumerate(rows[0])}
    need = ("詞", "搜尋量", "分類", "位階", "相關性", "狀態")
    missing = [c for c in need if c not in h]
    if missing:
        # 欄位被改名就講出來——靜默回空會讓標題默默退回沒有關鍵字的版本
        logger.warning(f"搜尋詞庫缺欄位 {missing}，本次不套用搜尋詞庫")
        return [], []
    out: list[Word] = []
    banned: list[str] = []
    for r in rows[1:]:
        if len(r) <= max(h.values()) or not r[h["詞"]].strip():
            continue
        if (r[h["狀態"]].strip() != "啟用"
                or r[h["相關性"]].strip() not in conf.relevance
                or r[h["位階"]].strip() in ("品牌", "錯字")):   # 死詞／泛用／他牌／錯字：可投廣告，不可進標題
            banned.append(r[h["詞"]].strip())
            continue
        try:
            vol = int(str(r[h["搜尋量"]]).replace(",", "").strip())
        except ValueError:
            continue
        out.append(Word(r[h["詞"]].strip(), vol, r[h["分類"]].strip(), r[h["位階"]].strip()))
    out.sort(key=lambda w: -w.量)
    logger.info(f"搜尋詞庫載入 {len(out)} 個可用詞（已排除泛用／品牌／死詞 {len(banned)} 個）")
    return out, banned


def _load(shop: str = "nail") -> list[Word]:
    return _load_rows(shop)[0]


def banned_words(shop: str = "nail") -> set[str]:
    """不可進標題的詞（泛用／他牌／死詞）。自家品牌詞（喬伊盧…）若被標品牌也會在這裡，呼叫端自行放行。"""
    return set(_load_rows(shop)[1])


# 需要 PIF 的品類（化粧品）：標題公式要放 ✅PIF合規（v2.2）。Lady 沒有這件事。
PIF_CATEGORIES = {"膠", "溶劑", "保養"}


def needs_pif(category: str, product_name: str = "", shop: str = "nail") -> bool:
    """標題要不要放 ✅PIF合規：Nail 的化粧品類（膠／溶劑／保養；卸甲只有膠液膏類，卸甲包不算）。"""
    conf = POOLS.get(str(shop).lower())
    if conf is not None and not conf.pif_categories:
        return False
    if category in PIF_CATEGORIES:
        return True
    return category == "卸甲" and any(w in (product_name or "") for w in ("膠", "液", "膏", "油"))


def first_line_candidates(p: "Pool", product_name: str, n: int = 8) -> list[str]:
    """第一行大詞候選：本類的詞，和品名有共同字眼的排前面，其餘依量。

    只看本類（不含「美甲」這種廣域詞，那個放尾段當保險）。實測「膠」池同時有
    貓眼指甲油／底膠／建構膠，只照量排會讓底膠商品開頭寫「貓眼指甲油」→ 先比字眼。
    """
    own = [w for w in p.words if p.分類 in {c.strip() for c in w.分類.split(",")}]
    name = product_name or ""
    grams = {name[i:i + 2] for i in range(len(name) - 1)}

    def hit(w):
        return any(w.詞[i:i + 2] in grams for i in range(len(w.詞) - 1))
    ranked = [w for w in own if hit(w)] + [w for w in own if not hit(w)]
    return [w.詞 for w in ranked[:n]]


def pool_for(product_name: str, category: str = "", extra: str = "", shop: str = "nail") -> Pool:
    """這支商品可用的搜尋詞庫＝該分類（Nail 再加「廣域」；Lady 刻意沒有廣域）。"""
    cat = category or category_of(product_name, extra, shop=shop)
    conf = POOLS.get(str(shop).lower())
    broad = bool(conf and conf.has_broad)
    seen: set[str] = set()
    words: list[Word] = []
    for w in _load(shop):
        cats = {c.strip() for c in w.分類.split(",") if c.strip()}
        if cat not in cats and not (broad and "廣域" in cats):
            continue
        if w.詞 in seen:
            continue
        seen.add(w.詞)
        words.append(w)
    return Pool(cat, words)


def prompt_block(product_name: str, category: str = "", extra: str = "",
                 n: int = 16, budget: int = 40, shop: str = "nail") -> str:
    """給文案 prompt 用的一段（標題 v2.2）：第一行大詞＋可用詞清單＋建議尾串。

    ⚠️ 只給「可以用的詞」，不解釋為什麼別的不能用——prompt 越短模型越照做。
    """
    p = pool_for(product_name, category, extra, shop=shop)
    if not p.words:
        return ""
    if needs_pif(p.分類, product_name, shop=shop):
        # 化粧品標題不可出現「療」（貓眼光療膠／光療指甲油都不行）→ 清單裡就不給
        p = Pool(p.分類, [w for w in p.words if "療" not in w.詞])
    # 第一行＝本類大詞（不算「美甲」這種廣域詞——那個放尾段當保險）
    vol = {w.詞: w.量 for w in p.words}
    cand = first_line_candidates(p, f"{product_name} {extra}")
    lines = [f"【可用關鍵字（{p.分類 or '廣域'}，依蝦皮實際搜尋量降冪）】"]
    lines += [f"　{w.詞}（{w.量}）" for w in p.words[:n]]
    if cand:
        lines.append("【第一行大詞候選】" + " ".join(f"{c}（{vol[c]}）" for c in cand)
                     + "\n　→ 從這裡挑**真正描述這支商品**、量最大的 1~2 個放標題最前面（大的在前），"
                       f"接著放這支商品自己的真實形態詞（例：{_FORM_EXAMPLES.get(str(shop).lower(), '')}），每支不同")
    lines.append(f"【建議尾串】{p.tail(budget)}")
    if needs_pif(p.分類, product_name, shop=shop):
        lines.append("【這支要放 ✅PIF合規】放在「大詞＋形態詞」之後、品牌之前；✅ 前面的內容要落在手機搜尋卡的第二行"
                     "（中文算 1 寬、英數與空格算 0.5 寬，✅ 前總寬 9.5~20）。膠類標題全文不可出現「療」字。")
    lines.append(f"只能用上面列出的詞；沒列的詞代表沒有搜尋量或不是{_AUDIENCE.get(str(shop).lower(), '本賣場')}客群，"
                 "不要自己發明。")
    # ⚠️ 同一類的詞裡本來就混著不同款式（女裝-褲 同時有 工裝褲／吊帶褲／西裝褲／連身褲）。
    #    湊字數把它們塞進來＝不實標示，而且引來的點擊不會轉換（2026-09-18 Lady 首跑實際發生）。
    lines.append("⚠️ 清單裡的詞**不是每個都能用**：只放「這支商品本身就是」的品類與形態詞。"
                 "別種款式的詞（例：闊腿褲不可寫 工裝褲／吊帶褲／西裝褲／連身褲；三角褲不可寫 丁字褲）"
                 "即使搜尋量很大也一律不放——那是不實標示。單字詞（女、褲）也不要放。")
    lines.append("標題**盡量填到 58-60 字**（60 字是免費版位），順序是：\n"
                 "　①**搜尋量優先**：把清單裡所有符合這支商品的詞放進去（含同義詞、倒裝寫法、真的有的顏色詞）\n"
                 "　②清單用完還不到 58 字 → **從這支商品自己的資料補**（材質、版型、機能、適用場合、規格數字），"
                 "例：亞麻、棉麻、高腰、直筒、垂感、薄款、無彈、透氣。這些詞要**在商品屬性或詳情裡找得到**，不可自行想像；"
                 "**一個詞一格、用半形空格分開**（寫「薄款 垂感 無彈」不要串成「薄款垂感無彈力」——蝦皮是逐詞分詞的）\n"
                 "　③兩者都用完仍不足就留短。**絕不可放別種款式的詞湊字數**（闊腿褲不可寫 工裝褲／吊帶褲／西裝褲）")
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
