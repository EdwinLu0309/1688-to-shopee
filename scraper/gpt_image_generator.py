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
