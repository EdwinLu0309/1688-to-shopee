"""Nail（美甲）SKU 品號生成器。

⚠️ **與 Lady 是兩套完全不同的體系，刻意不共用**（Edwin 2026-08-28 指示「三賣場不共用」）。
規則正本＝`1688-order/docs/上架訂貨統一架構.md`；本檔為 Nail 專用實作。

## 結構（15 碼）
```
A   A     006     0003    01     0000
│   │     │       │       │      └─ 顏色 4 碼：該「款式」底下的規格組合序（無規格＝0000）
│   │     │       │       └──────── 款式 2 碼：該商品底下的第幾個 1688 連結／品項
│   │     │       └──────────────── 商品序 4 碼：Edwin 認定的「同一個商品」
│   │     └──────────────────────── 品牌／小分類 3 碼（AS=006、VDN=012…）
│   └────────────────────────────── 大分類字母（取自商品編號 AAS1 的第一個 A）
└────────────────────────────────── 賣場碼（Nail = A）
```

## 商品編號自己也解得開
`AAS1` ＝ 大分類 `A` ＋ 品牌 `AS` ＋ 序號 `1`（`AVD1`=VDN、`AIL1`=Infin.Lin）。
⚠️ 與 Lady 的 `H-c2` 不同——**沒有連字號**，所以解析式不可共用。

## ⚠️ 商品序由「商品編號存不存在」決定，不需要額外欄位（2026-09-08 Edwin 釐清）
```
新編號（1-1 沒有）  →  開新商品序，款式從 01 起
既有編號（1-1 有）  →  用它現有的商品序，款式接在現有最大之後
```
Edwin 要在既有系列加東西時，**本來就會直接填既有編號**（AS 黑瓶加皮草封層就填 `AAS1`），
不會另給新編號。所以「新編號＋掛既有商品序」這種情況不存在 → 原本設計的「歸屬」欄
沒有作用，已移除。

**款式＝1688 頁面第一軸的每個品項**（實證 `AVD2` 一個編號一個網址底下有 16 個款式：
防翹結合劑／健甲加固膠／自動修護封層…），**顏色＝該品項底下的第二層規格**（無則 0000）。
⚠️ 款式與 1688 連結**不是**一對一——同一個連結常包很多品項，各佔一個款式。

## ⚠️ 發號一律取「現有最大 +1」，不補中間空號
既有品牌碼有跳號（001、004、006…，002/003 空著）。若補空號，新品號會排在既有品號
**前面** → SKU 表排序時第 2 列（陣列公式錨點）會被推走、K/O/P 三欄整片壞掉。
一律往最大值後面發，就永遠不會發生（Edwin 2026-09-07 同意）。

## ⚠️ 顏色序滿 4 碼要補零到 4 碼
既有資料有 55 列把顏色寫成 5 碼（`00010` 而非 `0010`，美潮48色 48 列＋VDN 6 列＋
Krisno 1 列），已於 2026-09-07 由 Edwin 全數刪除（都是售完商品）。新碼一律 4 碼。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger

SHOP_CODE = "A"          # 賣場碼：Nail
CODE_LEN = 15
_SEG = {                 # (start, end) 0-based
    "shop": (0, 1),
    "cat": (1, 2),
    "brand": (2, 5),
    "item": (5, 9),      # 商品序
    "style": (9, 11),    # 款式
    "color": (11, 15),   # 顏色
}


class BadNailCode(Exception):
    """商品編號不是 `{大分類字母}{品牌字母}{序號}` 的形式（例：AAS1、AVD3、AIL1）。"""


class UnknownBrand(Exception):
    """既有資料查不到這個品牌的代號——**不自己編號**，請 Edwin 指定。

    自己編會撞到別的品牌（品牌碼有跳號、002/003 空著），而撞號不會有任何錯誤訊息，
    只會讓兩個品牌的商品混在同一個號段裡。
    """


@dataclass
class NailProductCode:
    cat: str        # 大分類字母，如 A
    brand: str      # 品牌字母，如 AS
    seq: int        # 商品編號自己的序號，如 1（⚠️ 與品號的「商品序」不是同一回事）


def parse_product_code(code: str) -> NailProductCode:
    """`AAS1` → (cat='A', brand='AS', seq=1)；`AVD13` → (A, VD, 13)。"""
    m = re.fullmatch(r"\s*([A-Za-z])([A-Za-z]+)(\d+)\s*", code or "")
    if not m:
        raise BadNailCode(f"Nail 商品編號格式不符（預期像 AAS1 / AVD3）：{code!r}")
    return NailProductCode(cat=m.group(1).upper(), brand=m.group(2).upper(),
                           seq=int(m.group(3)))


def _seg(code: str, name: str) -> str:
    a, b = _SEG[name]
    return (code or "")[a:b]


def _seg_int(code: str, name: str) -> int | None:
    s = _seg(code, name)
    return int(s) if s.isdigit() else None


def build_code(cat: str, brand_code: str, item_seq: int, style_seq: int,
               color_seq: int) -> str:
    code = (f"{SHOP_CODE}{cat.upper()}{brand_code}"
            f"{item_seq:04d}{style_seq:02d}{color_seq:04d}")
    assert len(code) == CODE_LEN, f"Nail 品號長度異常：{code}"
    return code


@dataclass
class NailContext:
    """從既有 1-1 資料建的對照：品牌碼、各品牌最大商品序、各商品序既有款式。

    全部從實際資料推導，不寫死——品牌會增加、號段會變，寫死一定過期。
    """
    brand_code_of: dict[tuple[str, str], str] = field(default_factory=dict)
    max_brand_code: dict[str, int] = field(default_factory=dict)
    max_item_seq: dict[tuple[str, str], int] = field(default_factory=dict)
    styles_of: dict[tuple[str, str, int], set[int]] = field(default_factory=dict)
    item_seq_of_code: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_sku_rows(cls, sku_rows: list[list[str]]) -> "NailContext":
        """sku_rows＝SKU表 A~M（去表頭）。靠 B 品名前綴回推商品編號。"""
        ctx = cls()
        for r in sku_rows:
            if len(r) < 2 or not r[0] or not r[1]:
                continue
            code = r[0].strip()
            if len(code) != CODE_LEN:
                continue                       # 舊的 16 碼髒資料，不參與推導
            try:
                pc = parse_product_code(r[1].split("_")[0])
            except BadNailCode:
                continue                       # 品名前綴不是商品編號（品牌前綴的舊列）
            cat, brand = pc.cat, pc.brand
            bcode = _seg(code, "brand")
            item = _seg_int(code, "item")
            style = _seg_int(code, "style")
            if not bcode.isdigit() or item is None or style is None:
                continue

            ctx.brand_code_of.setdefault((cat, brand), bcode)
            ctx.max_brand_code[cat] = max(ctx.max_brand_code.get(cat, 0), int(bcode))
            k = (cat, bcode)
            ctx.max_item_seq[k] = max(ctx.max_item_seq.get(k, 0), item)
            ctx.styles_of.setdefault((cat, bcode, item), set()).add(style)
            ctx.item_seq_of_code.setdefault(r[1].split("_")[0].strip(), item)
        return ctx

    def brand_code(self, cat: str, brand: str) -> str:
        bc = self.brand_code_of.get((cat, brand))
        if not bc:
            nxt = self.max_brand_code.get(cat, 0) + 1
            raise UnknownBrand(
                f"既有資料查不到品牌「{brand}」（大分類 {cat}）的代號。"
                f"不自己編號以免撞號——請 Edwin 指定；照『最大+1』的話會是 {nxt:03d}。")
        return bc


@dataclass
class NailAllocation:
    spec1: str
    spec2: str
    sku_code: str
    reused: bool = False


@dataclass
class NailAllocResult:
    allocations: list[NailAllocation] = field(default_factory=list)
    reused: int = 0
    created: int = 0
    item_seq: int = 0
    style_seq: int = 0
    new_item: bool = True          # True＝開了新商品序


def _norm(s: str) -> str:
    """規格原文正規化：只壓多餘空白，**不轉繁簡、不改字**（原文是比對鍵）。"""
    return re.sub(r"\s+", " ", (s or "")).strip()


def allocate(product_code: str, specs: list[tuple[str, str]],
             existing: list, ctx: NailContext) -> NailAllocResult:
    """替 specs 配 Nail 品號。**商品序由「商品編號存不存在」決定**（見檔頭）。

    - 新編號 → 開新商品序（該品牌現有最大 +1）、款式從 01 起
    - 既有編號 → 用它現有的商品序、款式接在現有最大之後
    - append-only：同商品編號既有的規格原文沿用舊碼，新原文才發新號
    - existing 的元素需有 `.sku_code` / `.spec1` / `.spec2`（沿用 sku_code.ExistingRow）
    """
    pc = parse_product_code(product_code)
    bcode = ctx.brand_code(pc.cat, pc.brand)

    # ── 決定商品序與款式：編號存不存在說了算 ──
    item = ctx.item_seq_of_code.get(product_code.strip())
    if item is None:
        item = ctx.max_item_seq.get((pc.cat, bcode), 0) + 1   # 新編號 → 新商品序
        style = 1
        new_item = True
    else:
        used = ctx.styles_of.get((pc.cat, bcode, item), set())  # 既有編號 → 接款式
        style = (max(used) if used else 0) + 1
        new_item = False

    # ── 既有列：同規格原文沿用舊碼（append-only）──
    code_of: dict[tuple[str, str], str] = {}
    max_color = 0
    for r in existing:
        sc = getattr(r, "sku_code", "")
        if len(sc) != CODE_LEN:
            continue
        cseq = _seg_int(sc, "color")
        if cseq is None:
            continue
        max_color = max(max_color, cseq)
        code_of[(_norm(getattr(r, "spec1", "")), _norm(getattr(r, "spec2", "")))] = sc

    res = NailAllocResult(item_seq=item, style_seq=style, new_item=new_item)
    single = len(specs) == 1 and not _norm(specs[0][0]) and not _norm(specs[0][1])
    for raw1, raw2 in specs:
        s1, s2 = _norm(raw1), _norm(raw2)
        old = code_of.get((s1, s2))
        if old:
            res.allocations.append(NailAllocation(s1, s2, old, True))
            res.reused += 1
            continue
        if single:                      # 完全沒有規格的商品 → 顏色序 0000
            color = 0
        else:
            max_color += 1
            color = max_color
        code = build_code(pc.cat, bcode, item, style, color)
        code_of[(s1, s2)] = code
        res.allocations.append(NailAllocation(s1, s2, code, False))
        res.created += 1

    logger.info(f"[{product_code}] Nail 配號：品牌{bcode} 商品序{item:04d} 款式{style:02d}"
                f"（{'新編號→新商品序' if new_item else '既有編號→接款式'}）"
                f"｜沿用 {res.reused} / 新發 {res.created}")
    return res
