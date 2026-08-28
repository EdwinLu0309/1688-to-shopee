"""SKU 品號生成器（依各賣場自訂規則產 ERP 品號）。

規則正本＝`1688-order/docs/上架訂貨統一架構.md` §5-3。這裡只實作 Lady；
⚠️ **三家品號體系完全不同**（Lady 15碼B開頭／Nail 15碼A開頭但尾碼結構不同、品名前綴是
品牌碼 `CHE`／Baby 14位純數字），所以不做「共用一套、換參數」，未支援的賣場直接拋錯，
不猜、不硬套（猜錯會產生看起來合法但實際撞號的碼）。

Lady 結構（15 碼）：
```
BH003 0002 0006 03   ↔  H-c2_蝴蝶結素色三角褲_杏色,XL
│ │ │   │    │   └── 尺寸序 2 碼
│ │ │   │    └────── 顏色序 4 碼
│ │ │   └─────────── 款號 4 碼（商品編號 H-c2 的「2」補零）
│ │ └─────────────── 子分類 3 碼（字母序 a=001 b=002 c=003）
│ └───────────────── 分類字母（商品編號的「H」）
└─────────────────── 賣場碼（Lady=B）
```

⚠️ **顏色／尺寸序＝「我們實際要進貨販售的流水號」，不是 1688 頁面位置。**
既有資料看起來像位置編碼且跳號（0001,0002,0005…），實為「後來某些顏色不賣了刪掉」造成。

⚠️ **鐵律：號碼只發不改、刪掉的號不回收（append-only）。** 新號＝該商品現有最大號 + 1。
回收號碼會讓蝦皮歷史訂單／ERP 舊紀錄／獲利表 join **靜默串到錯的商品**（不報錯的錯）。

⚠️ **比對「這個選項是否已有碼」一律用 1688 原文**（SKU表 L 規格一／M 規格二），
不可用品名裡我們取的繁體名——`紫色`（我們）vs `067-卡其`（1688 原文），
拿繁體名去頁面找永遠找不到。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger

# 賣場碼。未列出的賣場＝規則尚未取得，generate 時拋 UnsupportedShop。
SHOP_PREFIX = {"lady": "B"}

CODE_LEN = 15
_SEG = {           # (start, end) 0-based，切片用
    "shop": (0, 1),
    "cat": (1, 2),
    "sub": (2, 5),
    "model": (5, 9),
    "color": (9, 13),
    "size": (13, 15),
}


class UnsupportedShop(Exception):
    """該賣場的品號規則尚未取得（Nail／Baby 體系與 Lady 完全不同，不可硬套）。"""


class BadProductCode(Exception):
    """商品編號不是 `{分類字母}-{子分類字母}{款號}` 的形式（例：H-c2、P-a101）。"""


@dataclass
class ProductCode:
    cat: str        # 分類字母，如 H
    sub: str        # 子分類字母，如 c
    model: int      # 款號，如 2

    @property
    def sub_seq(self) -> int:
        """子分類字母 → 字母序（a=1, b=2, c=3…）。"""
        return ord(self.sub.lower()) - ord("a") + 1


def parse_product_code(code: str) -> ProductCode:
    """`H-c2` → ProductCode(cat='H', sub='c', model=2)；`P-a101` → (P, a, 101)。"""
    m = re.fullmatch(r"\s*([A-Za-z])\s*-\s*([A-Za-z])(\d+)\s*", code or "")
    if not m:
        raise BadProductCode(f"商品編號格式不符（預期像 H-c2 / P-a101）：{code!r}")
    return ProductCode(cat=m.group(1).upper(), sub=m.group(2).lower(), model=int(m.group(3)))


def build_code(shop: str, product_code: str, color_seq: int, size_seq: int) -> str:
    """組出 15 碼品號。size_seq=0 代表單軸商品（無第二層選項）。"""
    prefix = SHOP_PREFIX.get(str(shop).lower())
    if not prefix:
        raise UnsupportedShop(
            f"賣場 {shop} 的 SKU 品號規則尚未取得（目前只有 Lady）。"
            f"三家體系完全不同，不可套用 Lady 規則——請先向 Edwin 取得該賣場規則。")
    pc = parse_product_code(product_code)
    code = f"{prefix}{pc.cat}{pc.sub_seq:03d}{pc.model:04d}{color_seq:04d}{size_seq:02d}"
    assert len(code) == CODE_LEN, f"品號長度異常：{code}"
    return code


def _seg_int(code: str, name: str) -> int | None:
    a, b = _SEG[name]
    part = (code or "")[a:b]
    return int(part) if part.isdigit() else None


@dataclass
class ExistingRow:
    """既有 SKU 表的一列（只取生碼需要的欄）。"""
    sku_code: str      # A 品號
    name: str          # B 品名
    spec1: str         # L 1688規格一（原文）
    spec2: str         # M 1688規格二（原文）


@dataclass
class Allocation:
    """一個選項組合的配號結果。"""
    spec1: str
    spec2: str
    sku_code: str
    color_seq: int
    size_seq: int
    reused: bool = False        # True＝沿用既有碼（append-only）


@dataclass
class AllocResult:
    allocations: list[Allocation] = field(default_factory=list)
    reused: int = 0
    created: int = 0


def _norm_spec(s: str) -> str:
    """規格原文正規化：只壓多餘空白，**不轉繁簡、不改字**（原文是比對鍵，動了就對不上）。"""
    return re.sub(r"\s+", " ", (s or "")).strip()


def allocate(shop: str, product_code: str,
             specs: list[tuple[str, str]],
             existing: list[ExistingRow]) -> AllocResult:
    """替 specs（(規格一原文, 規格二原文) 清單）配品號，append-only。

    - 既有相同原文組合 → 沿用既有品號，絕不重編
    - 新原文 → 顏色／尺寸各自取「該商品現有最大序 + 1」（刪掉的號不回收）
    - specs 的順序＝要進貨販售的順序（新號依此順序遞增）
    """
    prefix = SHOP_PREFIX.get(str(shop).lower())
    if not prefix:
        raise UnsupportedShop(
            f"賣場 {shop} 的 SKU 品號規則尚未取得（目前只有 Lady）。")
    pc = parse_product_code(product_code)          # 先驗，格式錯就別往下做

    # ── 從既有列建三張對照：原文→序號、原文組合→品號、目前最大序 ──
    color_seq_of: dict[str, int] = {}
    size_seq_of: dict[str, int] = {}
    code_of: dict[tuple[str, str], str] = {}
    max_color = 0
    max_size = 0
    for r in existing:
        cs, ss = _seg_int(r.sku_code, "color"), _seg_int(r.sku_code, "size")
        if cs is None or ss is None:
            continue                                # 不合本規則的舊列（別讓它污染配號）
        s1, s2 = _norm_spec(r.spec1), _norm_spec(r.spec2)
        max_color = max(max_color, cs)
        max_size = max(max_size, ss)
        if s1 and cs and s1 not in color_seq_of:
            color_seq_of[s1] = cs
        if s2 and ss and s2 not in size_seq_of:
            size_seq_of[s2] = ss
        if s1:
            code_of[(s1, s2)] = r.sku_code

    res = AllocResult()
    for raw1, raw2 in specs:
        s1, s2 = _norm_spec(raw1), _norm_spec(raw2)

        old = code_of.get((s1, s2))
        if old:                                     # ① 整組已存在 → 原碼奉還
            res.allocations.append(Allocation(
                s1, s2, old, _seg_int(old, "color") or 0, _seg_int(old, "size") or 0, True))
            res.reused += 1
            continue

        # ② 顏色：既有原文沿用，新原文取 max+1
        if s1 in color_seq_of:
            cseq = color_seq_of[s1]
        else:
            max_color += 1
            cseq = max_color
            color_seq_of[s1] = cseq

        # ③ 尺寸：同理；沒有第二軸的商品固定 0
        if not s2:
            sseq = 0
        elif s2 in size_seq_of:
            sseq = size_seq_of[s2]
        else:
            max_size += 1
            sseq = max_size
            size_seq_of[s2] = sseq

        code = build_code(shop, product_code, cseq, sseq)
        code_of[(s1, s2)] = code
        res.allocations.append(Allocation(s1, s2, code, cseq, sseq, False))
        res.created += 1

    if res.reused:
        logger.info(f"[{product_code}] 配號：沿用 {res.reused} / 新發 {res.created}")
    return res


def collect_existing(sku_rows: list[list[str]], product_code: str) -> list[ExistingRow]:
    """從 SKU 表原始列（A~M，1-based 表頭已去除）挑出屬於該商品編號的列。

    判斷依據＝B 品名的 `^[^_]+` 前綴（與 SKU表 K/O/P 公式同一套解析法）。
    """
    want = (product_code or "").strip()
    out: list[ExistingRow] = []
    for r in sku_rows:
        if len(r) < 2 or not r[0] or not r[1]:
            continue
        if r[1].split("_")[0].strip() != want:
            continue
        out.append(ExistingRow(
            sku_code=r[0].strip(),
            name=r[1].strip(),
            spec1=r[11] if len(r) > 11 else "",
            spec2=r[12] if len(r) > 12 else "",
        ))
    return out
