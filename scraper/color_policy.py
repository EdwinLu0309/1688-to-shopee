"""
顏色政策（第二層）：從第一層（款式備註）留下的顏色裡，只挑「百搭中性色」，
砍掉流行色（粉/黃/綠/紫/橙/天藍…不進貨），最多留 max_n（預設 5）。

原則（跟 Edwin 對齊）：尺寸全留、顏色壓；砍顏色不砍尺寸（可替代性：尺寸不對無法替換）。
中性色不足就留原數（寧缺勿濫、不硬湊流行色）；一支都沒中性色 → 標記人工決定。

中性色定義（由 Edwin 拍板）：黑 / 白(含米白象牙) / 米杏卡其 / 灰 / 藏青深藍 / 駝咖啡棕；
其餘（粉紅黃綠紫橙 + 天藍湖藍釉藍等非藏青的藍 + 軍綠）一律當流行色丟。
"""
import re

# 中性色分層（由具體到一般；順序＝蝦皮上顯示/優先保留順序）。simp+trad 都放。
_NEUTRAL_TIERS = [
    ["黑"],                                                        # 黑
    ["白", "象牙", "本白", "奶白", "奶芙", "牙白", "漂白"],          # 白（米白含「白」也落這層）
    ["米", "杏", "卡其", "卡奇", "咔叽", "咖其"],                    # 米/杏/卡其
    ["灰"],                                                        # 灰
    ["藏青", "藏蓝", "藏藍", "深蓝", "深藍", "丈青", "藏靑", "黛蓝", "黛藍"],  # 藏青/深藍
    ["驼", "駝", "咖啡", "咖", "棕", "大地", "焦糖", "可可"],         # 駝/咖啡/棕
]


def _clean(name: str) -> str:
    """去掉款式括號贅字（「米白色【长裤】」→「米白色」）。"""
    return re.sub(r"[【\[（(][^】\]）)]*[】\]）)]", "", name or "").strip()


# 身高款/版型/季節 token——這些跟「尺寸」同性質（合身維度），全留，不當顏色砍。
# 拆底色時把它們剝掉，只留純顏色來判斷中性與否。
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


def neutral_tier(name: str) -> int | None:
    """回傳中性色分層 index（越小越優先）；非中性色回 None。"""
    s = _clean(name)
    for i, kws in enumerate(_NEUTRAL_TIERS):
        if any(k in s for k in kws):
            return i
    return None


def pick_neutral_colors(color_keys: list[str], color_map: dict | None = None,
                        max_n: int = 5) -> dict:
    """從 color_keys 挑中性色（優先序 + 最多 max_n）。

    color_map：{原始色卡 key: 繁體乾淨名}（有就用繁體名判斷，較準）。
    回傳 {selected, dropped_fashion, dropped_overflow, n_neutral, flag}。
    - selected：要保留的原始 key（依中性優先序）
    - dropped_fashion：被當流行色砍掉的（不進貨）
    - dropped_overflow：中性色超過 max_n 被砍的
    - flag：一支都沒中性色時給提示字串，否則 None
    """
    color_map = color_map or {}
    scored = []  # (tier, orig_index, key)
    fashion = []
    for idx, key in enumerate(color_keys):
        name = color_map.get(key, key)
        tier = neutral_tier(name)
        if tier is None:
            fashion.append(key)
        else:
            scored.append((tier, idx, key))

    scored.sort(key=lambda t: (t[0], t[1]))  # 中性優先序，再原始順序

    # 先「每個色系挑一個」（黑白米灰藏青卡其 求分散，不要兩件白擠掉灰/藏青），
    # 名額有剩再回頭補同色系的第二件。
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

    flag = None
    if not scored:
        flag = "0 中性色（全是流行色）→ 需人工決定要不要上、上哪些色"
    return {
        "selected": selected,
        "dropped_fashion": fashion,
        "dropped_overflow": overflow,
        "n_neutral": len(scored),
        "flag": flag,
    }


def select_first_axis(tier1_keys: list[str], color_map: dict, n_sizes: int,
                      max_base_colors: int = 5, sku_cap: int = 100) -> dict:
    """挑第一軸選項（第一軸＝顏色 × 身高款/版型）。

    政策：**身高款當尺寸看，全留**（合身維度不砍）；只砍**底色**到中性色 ≤ max_base_colors，
    再用 sku_cap 保底（同底色的身高款整組綁著留或整組砍，不拆散）。

    回傳 {selected（要保留的第一軸 key）, kept_bases, dropped_fashion, dropped_overflow,
          n_base_colors, n_options, flag}。
    """
    n_sizes = max(1, n_sizes)
    key_base = {k: (base_color(color_map.get(k, k)) or k) for k in tier1_keys}

    bases_in_order = []
    for k in tier1_keys:
        if key_base[k] not in bases_in_order:
            bases_in_order.append(key_base[k])

    # 底色做中性判斷 + 分散排序（取全部中性底色的優先序）
    pick = pick_neutral_colors(bases_in_order, max_n=len(bases_in_order) or 1)
    neutral_bases = pick["selected"]          # 全部中性底色，已依優先序
    fashion_bases = set(pick["dropped_fashion"])

    # 依優先序貪婪加底色：不超過 max_base_colors，且 (選項數 × 尺碼) ≤ sku_cap
    kept_bases, running_opts = [], 0
    for b in neutral_bases:
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
