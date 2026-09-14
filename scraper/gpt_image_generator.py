"""[已搬到 ecommerce-media #S130] 相容 shim — re-export ecommerce_media.image_gen。

真碼在 ecommerce-media（第二包）。本檔只做兩件事：
1. 把設計資料夾（design_engine md / 板娘 / 對手圖＝品牌政策）指回本 repo 的 config/design_engine。
2. re-export image_gen 的公開 + 既有呼叫端用到的私有名（batch_pipeline2 / scratch_*）。
"""
import os as _os
from pathlib import Path as _Path

# 品牌設計資料留本 repo；env 未設才指回（不覆蓋外部已設的）
_os.environ.setdefault(
    "ECOMMERCE_DESIGN_DIR",
    str(_Path(__file__).resolve().parent.parent / "config" / "design_engine"),
)

from ecommerce_media.image_gen import (  # noqa: E402,F401
    MODEL, SIZE, QUALITY,
    DESIGN_DIR, PERSONA_DIR, REFERENCE_DIR, _IMG_EXT,
    load_design_spec, generate_cover,
    _client, _imgs, _normalize, _edit,
)

# ── 圖片模板（2026-09-15）──────────────────────────────────────
# 上游 `load_design_spec()` 是「讀 DESIGN_DIR 底下**所有** md 串起來」，沒有賣場也沒有模板的概念
# → Nail/Baby 勾 ✨GPT 會拿到**女裝**的規範（人物比例、模特兒位置、穿搭情境），套在集塵器上
#   會生出很怪的圖。沒人踩到只是因為至今沒有非 Lady 的批次勾過 GPT。
# 這裡不改上游，改成執行前把 DESIGN_DIR 指到「該賣場／該模板」那一份。
from contextlib import contextmanager as _contextmanager  # noqa: E402
from pathlib import Path as _P  # noqa: E402

import ecommerce_media.image_gen as _ig  # noqa: E402


def design_templates(shop: str) -> list[_P]:
    """該賣場有哪幾份圖片模板（config/design_engine/{shop}/*.md）。加一份 md 就多一個選項。"""
    d = _P(DESIGN_DIR) / shop
    return sorted(d.glob("*.md")) if d.exists() else []


@_contextmanager
def use_template(shop: str, template: str | None = None):
    """把生圖規範切到 {shop}/{template}.md；沒指定就用該賣場資料夾裡的全部 md。

    ⚠️ `load_design_spec()` 讀的是 module-level 的 DESIGN_DIR，所以只能在呼叫前換掉它
    （改 env 沒用——那在 import 當下就定案了）。用完一定要還原，否則同一個 process
    跑第二個賣場會沿用上一家的規範。
    """
    orig = _ig.DESIGN_DIR
    target = _P(DESIGN_DIR) / shop
    tmp = None
    try:
        if template:
            src = target / f"{template}.md"
            if not src.exists():
                raise FileNotFoundError(f"找不到圖片模板：{src}")
            import tempfile, shutil
            tmp = _P(tempfile.mkdtemp(prefix="design_"))
            shutil.copy2(src, tmp / src.name)
            _ig.DESIGN_DIR = tmp
        elif target.exists():
            _ig.DESIGN_DIR = target
        else:
            raise FileNotFoundError(
                f"{shop} 還沒有圖片設計規範（config/design_engine/{shop}/*.md）——"
                f"沒有規範就沒有風格依據，不要拿別家的規範生圖")
        yield _ig.DESIGN_DIR
    finally:
        _ig.DESIGN_DIR = orig
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
