"""[已搬到 ecommerce-media #S130] 相容 shim — re-export ecommerce_media.video。"""
from ecommerce_media.video import (  # noqa: F401
    collect_images, make_product_video, build_ffmpeg_args,
)
