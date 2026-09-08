"""1688 商品頁「長/寬/高/體積/重量(g)」表 → 上架 Excel 的重量（kg）。

⚠️ **抓不到就留空、大聲 warning，絕不可退回寫死的 0.1kg**（2026-09-08 #S226）：
假重量會讓蝦皮運費與獲利表的結構版國際運費一起算錯，而且**看起來像真的**——
同「空白會在下游變成假數字」那條。實例：桌上型雙渦輪集塵器被填成 0.1kg。

解析規則移植自 `1688-order/order/weight_scraper.py`（該檔寫 SKU 表 Q 欄的單件重量，
規則已在 Lady 189 支／1,144 SKU 上驗過），這裡只取「全品單一重量」與「規格表眾數」
兩個層級——上架 Excel 的重量是 per-商品 一個值，不需要 per-SKU 的四級配對。
"""
from __future__ import annotations

import re
from collections import Counter

from loguru import logger

# ⚠️ 1000g 整數＝1688 賣家沒填重量時的預設哨兵值（Lady 實測 4 支內衣全是 1000）
SENTINEL_G = 1000.0
_SKIP_HEADERS = ("长", "宽", "高", "体积", "長", "寬", "體積")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def parse_weight_g(tables: list[str] | None) -> float | None:
    """從抓到的重量表文字取「這支商品的克數」；取不到回 None（呼叫端負責喊）。

    兩種版面：
    - 「重量(g)」自成一行 → 下一行就是數值（全品單一重量）
    - 表格有規格欄 + 重量欄 → 收所有列，取**眾數**（同一支商品各規格多半同重量；
      眾數比平均耐得住個別離群值）
    """
    if not tables:
        return None
    singles: list[float] = []
    per_spec: list[float] = []

    for text in tables:
        lines = [ln for ln in (text or "").split("\n") if ln.strip()]
        hi = next((i for i, ln in enumerate(lines)
                   if re.search(r"重量\s*\(?(g|克)\)?", ln)), None)
        if hi is None:
            continue
        hdr = lines[hi].split("\t")
        if len(hdr) == 1:                       # 「重量(g)」單獨一行
            if hi + 1 < len(lines):
                m = re.search(r"[\d.]+", lines[hi + 1])
                if m:
                    singles.append(float(m.group(0)))
            continue
        widx = next((j for j, h in enumerate(hdr) if "重量" in h), None)
        if widx is None:
            continue
        for ln in lines[hi + 1:]:
            cells = ln.split("\t")
            if len(cells) != len(hdr):
                continue
            try:
                per_spec.append(float(cells[widx]))
            except ValueError:
                continue

    for pool in (per_spec, singles):            # 規格表優先（比較具體）
        vals = [g for g in pool if 0 < g < 100000 and g != SENTINEL_G]
        if vals:
            return Counter(vals).most_common(1)[0][0]

    if any(g == SENTINEL_G for g in per_spec + singles):
        logger.warning("重量表只有 1000g（＝1688 賣家沒填的哨兵值）→ 視為未填")
    return None


def weight_kg(data: dict, code: str = "") -> float | None:
    """抓取結果 dict → 重量(kg，四捨五入 3 位)；取不到回 None 並 warning。"""
    g = parse_weight_g(data.get("weight_tables"))
    if g is None:
        logger.warning(f"[{code or data.get('item_id')}] 1688 頁面沒有重量表 → "
                       f"上架 Excel 的重量欄留空，**請手動補**（運費會算錯）")
        return None
    kg = round(g / 1000, 3)
    tag = code or data.get("item_id")
    # ⚠️ 「重量(g)」自成一行＝該頁只給了一個總重，沒有 per-規格。這一頁若在名單裡被
    #    拆成多個蝦皮商品（HNV11：吸塵器/二合一打磨機/濾網 共用 offer 760973597185，
    #    整頁只寫 200g），三個商品會拿到同一個重量——對濾網合理，對 3,143 元的
    #    打磨機顯然不對。照寫但要喊出來，讓人回頭挑掉離譜的那幾支。
    single_only = any(len(ln.split("\t")) == 1
                      for tb in (data.get("weight_tables") or [])
                      for ln in tb.split("\n")
                      if re.search(r"重量\s*\(?(g|克)\)?", ln))
    if single_only:
        logger.warning(f"[{tag}] 該 1688 頁只給「全品單一重量」{g:g}g（沒有 per-規格）→ "
                       f"同頁的每個品項都會拿到 {kg}kg，重的那幾支請自行覆蓋")
    else:
        logger.info(f"[{tag}] 1688 頁面重量 {g:g}g → {kg}kg")
    return kg


# ── 長/寬/高（cm）──────────────────────────────────────────────
# 蝦皮模板有 AC/AD/AE 三欄。**這三欄比重量可靠**——實測 HNV7 集塵器重量欄是
# 哨兵值 1000g，但長寬高（39.5×21×6.5）是賣家真的填的。材積也是運費的依據之一，
# 有就填，讓 Edwin 只剩「補重量」一件事。
_DIM_HEADERS = {"length": ("长", "長"), "width": ("宽", "寬"), "height": ("高",)}


def parse_dims_cm(tables: list[str] | None) -> dict[str, float]:
    """從同一張表取長/寬/高（cm），取眾數；沒有的鍵就不出現。"""
    if not tables:
        return {}
    pools: dict[str, list[float]] = {k: [] for k in _DIM_HEADERS}
    for text in tables:
        lines = [ln for ln in (text or "").split("\n") if ln.strip()]
        hi = next((i for i, ln in enumerate(lines)
                   if re.search(r"重量\s*\(?(g|克)\)?", ln)), None)
        if hi is None:
            continue
        hdr = lines[hi].split("\t")
        if len(hdr) == 1:
            continue
        idx: dict[str, int] = {}
        for key, prefixes in _DIM_HEADERS.items():
            for j, h in enumerate(hdr):
                hs = h.strip()
                # 「高(cm)」要比對開頭，否則「高」會誤中「高度体积」之類
                if any(hs.startswith(px) for px in prefixes) and "体积" not in hs and "體積" not in hs:
                    idx[key] = j
                    break
        for ln in lines[hi + 1:]:
            cells = ln.split("\t")
            if len(cells) != len(hdr):
                continue
            for key, j in idx.items():
                try:
                    v = float(cells[j])
                except ValueError:
                    continue
                if 0 < v < 1000:
                    pools[key].append(v)
    return {k: Counter(v).most_common(1)[0][0] for k, v in pools.items() if v}


# ⚠️ 有賣家把 mm 填進「长(cm)」欄：實測 HNL23 光療燈寫 281×191×125（＝一台 2.8 公尺的
#    美甲燈，連 1688 自己算的體積都變成 6.7 立方公尺）、HNL26 寫 168×68×44。
#    **不自作聰明除以 10** —— 沒有原始事實可查時就不要猜（同「對不齊時寧可留空給人填」）。
#    整組丟掉並把原始數字印出來讓人補；重量不受影響（1350g 本身是對的）。
MAX_PLAUSIBLE_CM = 150


def dims_cm(data: dict, code: str = "") -> dict[str, float]:
    d = parse_dims_cm(data.get("weight_tables"))
    if not d:
        return {}
    tag = code or data.get("item_id")
    if any(v > MAX_PLAUSIBLE_CM for v in d.values()):
        logger.warning(
            f"[{tag}] 1688 頁面尺寸 {d.get('length','?')}×{d.get('width','?')}"
            f"×{d.get('height','?')} 不合理（>{MAX_PLAUSIBLE_CM}cm）——賣家很可能把 mm "
            f"填進 cm 欄。整組不寫、留空給人補（除以 10 大概是 "
            f"{'×'.join(f'{v/10:g}' for v in (d.get('length',0), d.get('width',0), d.get('height',0)))} cm，"
            f"但這是推測、不代寫）")
        return {}
    logger.info(f"[{tag}] 1688 頁面尺寸 "
                f"{d.get('length','?')}×{d.get('width','?')}×{d.get('height','?')} cm")
    return d
