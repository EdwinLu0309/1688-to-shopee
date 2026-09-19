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
    load_design_spec, generate_cover, generate_image, list_images,
    _client, _imgs, _normalize, _edit,
)

# 圖片模板（哪份提示、生幾張、帶不帶板娘）改由 scraper/image_templates.py 處理（2026-09-19）：
# 它自己讀模板、組好每一張的指令再呼叫 ecommerce_media.image_gen.generate_image。
# 舊的「偷換 DESIGN_DIR 讓上游只讀一份 md」寫法已拿掉。
