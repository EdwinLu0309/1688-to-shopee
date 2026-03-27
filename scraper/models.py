from dataclasses import dataclass, field
from typing import Any


@dataclass
class SKUOption:
    sku_id: str
    attributes: dict[str, str]
    price: float
    stock: int
    selected: bool = False


@dataclass
class Product1688:
    item_id: str
    title: str
    description: str
    main_images: list[str]
    detail_images: list[str]
    skus: list[SKUOption]
    min_order: int
    shop_name: str
    raw_url: str
    raw_sku_data: Any = field(default=None, repr=False)
