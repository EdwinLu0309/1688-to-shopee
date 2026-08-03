"""[已搬到 ecommerce-media #S130] 相容 shim — re-export ecommerce_media.image_host。"""
from ecommerce_media.image_host import (  # noqa: F401
    is_configured, upload_image, upload_images,
)
