"""
顏色政策（第二層）：從第一層（款式備註）留下的顏色裡，只挑「熱門好賣色」，
砍掉亮色系（亮綠/亮藍 + 粉黃紫橙紅），最多留 max_n（預設 5）。

原則（Edwin 拍板）：尺寸全留、身高款全留（合身維度）；只砍顏色。

熱門保留色（Edwin 指定的 11 個會買的色）：
  黑 / 白 / 灰 / 米 / 咖啡 / 大地 / 藏青 / 卡其 / 軍綠 / 牛仔藍 / 深藍
判斷關鍵——同一色相看「修飾詞」分熱門 vs 亮色：
  - 藍：預設熱門色留（丹寧藍/復古藍/牛仔藍/深藍/藏青…廠商描述再多都還是藍）；
        只有「亮/淺藍」(天藍/湖藍/寶藍/蔚藍/亮藍/冰藍/電光/克萊因/釉藍…) 才砍。
  - 綠：預設砍；只有「暗綠」(軍綠/墨綠/橄欖/苔綠) 才留。
  - 粉 / 黃 / 紫 / 橙 / 紅：一律砍。
"""
import re

# 亮色系藍（要砍）——藍多數是熱門色留著，只有這些亮/淺藍砍。先比這個，再比保留層。
_BRIGHT_BLUE = [
    "天蓝", "天藍", "湖蓝", "湖藍", "宝蓝", "寶藍", "蔚蓝", "蔚藍", "海蓝", "海藍",
    "亮蓝", "亮藍", "浅蓝", "淺藍", "淡蓝", "淡藍", "冰蓝", "冰藍", "电光", "電光",
    "克莱因", "克萊因", "碧蓝", "碧藍", "湖水", "孔雀", "釉蓝", "釉藍", "荧光蓝", "螢光藍",
    "果冻蓝", "果凍藍", "薄荷蓝", "薄荷藍",
]

# 熱門保留色分層（priority 由具體到一般；順序≈蝦皮顯示/優先保留序）。simp+trad 都放。
_HOT_TIERS = [
    ["黑"],                                                              # 黑
    ["白", "象牙", "奶白", "奶芙", "牙白", "漂白", "燕麦白", "燕麥白", "本白"],  # 白（米白含「白」也落此）
    ["米", "杏"],                                                        # 米/杏
    ["卡其", "卡奇", "咔叽", "咖其"],                                      # 卡其
    ["灰"],                                                              # 灰（含灰綠/霧霾灰藍等霧霾色）
    ["驼", "駝", "咖啡", "咖", "棕", "大地", "焦糖", "可可", "摩卡"],        # 咖啡/駝/棕/大地
    ["藏青", "藏蓝", "藏藍", "深蓝", "深藍", "牛仔", "丹宁", "丹寧",         # 藍（亮藍已先被砍，其餘藍都留）
     "复古蓝", "復古藍", "靛", "墨蓝", "墨藍", "钢蓝", "鋼藍",
     "雾霾蓝", "霧霾藍", "蓝", "藍"],
    ["军绿", "軍綠", "墨绿", "墨綠", "橄榄", "橄欖", "苔绿", "苔綠",         # 暗綠（亮綠不留）
     "橄绿", "橄綠", "灰绿", "灰綠"],
]


def _clean(name: str) -> str:
    """去掉款式括號贅字（「米白色【长裤】」→「米白色」）。"""
    return re.sub(r"[【\[（(][^】\]）)]*[】\]）)]", "", name or "").strip()


# 身高款/版型/季節 token——這些跟「尺寸」同性質（合身維度），全留，不當顏色砍。
# 拆底色時把它們剝掉，只留純顏色來判斷保留與否。
_VARIANT_TOKENS = [
    "常规款", "常規款", "高个子", "高個子", "小个子", "小個子",
    "加绒", "加絨", "加厚", "薄款", "厚款", "常规", "常規",
    "升级面料", "升級面料", "常规版", "常規版", "标准款", "標準款",
]


def base_color(name: str) -> str:
    """把第一軸選項名剝成純底色：去括號贅字 + 剝身高款/版型 token + 去分隔符。

    「（升级面料）-黑色-常规款」→「黑色」；「复古蓝【高个子】」→「复古蓝」。
    """
    s = _clean(name)
    s = re.sub(r"[-－/／、\s]+", " ", s)
    for t in _VARIANT_TOKENS:
        s = s.replace(t, " ")
    return re.sub(r"\s+", "", s).strip()


def hot_color_tier(name: str) -> int | None:
    """回傳熱門保留色分層 index（越小越優先）；亮色系/其他色回 None（要砍）。"""
    s = _clean(name)
    if any(q in s for q in _BRIGHT_BLUE):   # 亮藍先砍（否則會被下面的「藍」誤留）
        return None
    for i, kws in enumerate(_HOT_TIERS):
        if any(k in s for k in kws):
            return i
    return None  # 粉/黃/紫/橙/紅 + 亮綠/一般綠 + 其他 → 砍


def pick_hot_colors(color_keys: list[str], color_map: dict | None = None,
                    max_n: int = 5) -> dict:
    """從 color_keys 挑熱門保留色（優先序 + 色系分散 + 最多 max_n）。

    回傳 {selected, dropped_fashion, dropped_overflow, n_hot, flag}。
    """
    color_map = color_map or {}
    scored, fashion = [], []
    for idx, key in enumerate(color_keys):
        tier = hot_color_tier(color_map.get(key, key))
        if tier is None:
            fashion.append(key)
        else:
            scored.append((tier, idx, key))
    scored.sort(key=lambda t: (t[0], t[1]))

    # 先每個色系挑一個（求分散，不要兩件白擠掉灰/藍），有剩再補同色系第二件。
    by_tier: dict[int, list[str]] = {}
    for tier, _, key in scored:
        by_tier.setdefault(tier, []).append(key)
    selected = []
    for tier in sorted(by_tier):
        selected.append(by_tier[tier][0])
        if len(selected) >= max_n:
            break
    if len(selected) < max_n:
        for _, _, key in scored:
            if key not in selected:
                selected.append(key)
                if len(selected) >= max_n:
                    break
    overflow = [k for _, _, k in scored if k not in selected]

    flag = None if scored else "0 熱門色（全是亮色系）→ 需人工決定要不要上、上哪些色"
    return {"selected": selected, "dropped_fashion": fashion,
            "dropped_overflow": overflow, "n_hot": len(scored), "flag": flag}


def select_first_axis(tier1_keys: list[str], color_map: dict, n_sizes: int,
                      max_base_colors: int = 5, sku_cap: int = 100) -> dict:
    """挑第一軸選項（第一軸＝顏色 × 身高款/版型）。

    政策：**身高款當尺寸看，全留**（合身維度不砍）；只砍**底色**到熱門色 ≤ max_base_colors，
    再用 sku_cap 保底（同底色的身高款整組綁著留或整組砍，不拆散）。

    回傳 {selected, kept_bases, dropped_fashion, dropped_overflow,
          n_base_colors, n_options, flag}。
    """
    n_sizes = max(1, n_sizes)
    key_base = {k: (base_color(color_map.get(k, k)) or k) for k in tier1_keys}

    bases_in_order = []
    for k in tier1_keys:
        if key_base[k] not in bases_in_order:
            bases_in_order.append(key_base[k])

    pick = pick_hot_colors(bases_in_order, max_n=len(bases_in_order) or 1)
    hot_bases = pick["selected"]              # 全部熱門底色，已依優先序
    fashion_bases = set(pick["dropped_fashion"])

    # 依優先序貪婪加底色：不超過 max_base_colors，且 (選項數 × 尺碼) ≤ sku_cap
    kept_bases, running_opts = [], 0
    for b in hot_bases:
        if len(kept_bases) >= max_base_colors:
            break
        nvar = sum(1 for k in tier1_keys if key_base[k] == b)
        if kept_bases and (running_opts + nvar) * n_sizes > sku_cap:
            continue  # 這個底色的身高款整組放不下 → 跳過試更小的
        kept_bases.append(b)
        running_opts += nvar

    kept_set = set(kept_bases)
    selected = [k for k in tier1_keys if key_base[k] in kept_set]
    dropped_fashion = [k for k in tier1_keys if key_base[k] in fashion_bases]
    dropped_overflow = [k for k in tier1_keys
                        if key_base[k] not in kept_set and key_base[k] not in fashion_bases]

    return {
        "selected": selected,
        "kept_bases": kept_bases,
        "dropped_fashion": dropped_fashion,
        "dropped_overflow": dropped_overflow,
        "n_base_colors": len(kept_bases),
        "n_options": len(selected),
        "flag": pick["flag"],
    }
