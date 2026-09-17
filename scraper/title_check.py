"""Nail 標題 v2.2 的程式檢查（2026-09-17）。

規範寫得再清楚，模型還是會漏（實測：HNV7 標題吃進簡體「美规」、AI 自己加回編號）。
能機械判斷的就用程式做，分兩種：

- **直接修掉**（沒有判斷空間）：商品編號、✅ 以外的符號、免運/出貨/現貨/隔日、搜尋詞庫標成
  泛用／他牌／死詞的整詞、重複的詞、超過 60 字時從尾串砍。修完照樣記一筆，讓人知道 AI 原本寫了什麼。
- **只提醒**（要人看）：超過 60 字／少於 55 字、膠類出現「療」、✅ 位置不在第二行、
  標題裡的規格數字在來源資料找不到（一頁多款最常見的不實標示）。

規範正本：~/Downloads/NAIL_標題優化規範_v2.2_2026-09-16.md；SOP：config/sop/nail/…v1.0.md §2。
"""
from __future__ import annotations

import re
import unicodedata

MAX_LEN, MIN_OK, TARGET = 60, 55, 58
PIF_MARK = "✅PIF合規"
PROMO_WORDS = ("免運", "出貨", "現貨", "隔日", "快速出貨", "24H")
# 蝦皮搜尋卡：本賣場有「蝦皮優選」徽章，第一行 ≈9.5 寬、第二行 ≈12 寬（v2.2 §一）
WIDTH_MIN, WIDTH_MAX = 9.5, 20.0
_SYMBOLS = re.compile(r"[【】\[\]｜|！!★☆◆◇●○■□♥❤✨🔥⭐️※＊*#＃~～「」『』<>《》、，,。．:：;；/／+＋]")


def display_width(text: str) -> float:
    """中文／全形＝1、英數與空格＝0.5（v2.2 用 east_asian_width 算換行）。"""
    return sum(1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.5 for ch in text)


def check_title(title: str, *, code: str = "", pif: bool = False,
                banned: set[str] | None = None, spec_sources: list[str] | None = None,
                allow: set[str] | None = None) -> tuple[str, list[str], list[str]]:
    """回 (修正後標題, 已自動修掉的, 要人看的)。"""
    fixed, warn = [], []
    t = (title or "").replace("　", " ")

    # ✅ 以外的符號（先把 ✅ 保護起來）
    t2 = _SYMBOLS.sub(" ", t.replace("✅", "\0")).replace("\0", "✅")
    if t2 != t:
        fixed.append("拿掉符號")
    t = t2

    toks = [x for x in t.split() if x]
    out = []
    banned = banned or set()
    allow = allow or set()
    for tok in toks:
        if code and tok.upper() == code.upper():
            fixed.append(f"拿掉商品編號「{tok}」")
            continue
        if any(w in tok for w in PROMO_WORDS):
            fixed.append(f"拿掉促銷詞「{tok}」")
            continue
        if tok in banned and tok not in allow:
            fixed.append(f"拿掉不可進標題的詞「{tok}」（泛用／他牌／死詞）")
            continue
        if tok in out:            # 同一個詞寫兩次（實測 AAS13 尾巴又補了一次「封層 底膠」）＝浪費版位
            fixed.append(f"拿掉重複的「{tok}」")
            continue
        out.append(tok)
    # 超過 60 字：從尾巴拿掉詞（尾串是量最小、最不重要的那段；前段的大詞/形態/✅ 不動）
    dropped = []
    while len(" ".join(out)) > MAX_LEN and len(out) > 1 and "✅" not in out[-1]:
        dropped.insert(0, out.pop())
    if dropped:
        fixed.append(f"超過 {MAX_LEN} 字，從尾串拿掉「{' '.join(dropped)}」")
    t = " ".join(out)

    n = len(t)
    if n > MAX_LEN:
        warn.append(f"標題 {n} 字，超過 {MAX_LEN} 字上限（蝦皮會擋）")
    elif n < MIN_OK:
        warn.append(f"標題只有 {n} 字（目標 {TARGET}~{MAX_LEN}），可以再補搜尋詞庫裡的詞")

    if pif:
        if PIF_MARK not in t:
            warn.append("膠類／化粧品標題沒有「✅PIF合規」")
        else:
            w = display_width(t.split("✅", 1)[0])
            if not (WIDTH_MIN <= w <= WIDTH_MAX):
                warn.append(f"✅PIF合規 前面寬度 {w:g}（要 {WIDTH_MIN:g}~{WIDTH_MAX:g} 才會落在手機搜尋卡第二行）")
        if "療" in t:
            warn.append("膠類標題出現「療」字（v2.2 禁止；光撩非光療的測試版不走自動上架）")
    elif "✅" in t:
        warn.append("非化粧品標題出現 ✅（✅ 只用在 PIF合規 前面）")

    if spec_sources is not None:
        from scraper.keyword_pool import unverified_specs
        bad = unverified_specs(t, spec_sources)
        if bad:
            warn.append(f"標題規格 {'、'.join(bad)} 在 1688 規格名／名單找不到出處（可能是同頁別款的規格）")
    return t, fixed, warn
