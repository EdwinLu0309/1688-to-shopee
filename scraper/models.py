from dataclasses import dataclass, field
from typing import Any


@dataclass
class PriceRange:
    min_qty: int
    max_qty: int  # -1 means unlimited
    price: float


@dataclass
class SKUOption:
    sku_id: str
    attributes: dict[str, str]
    price: float
    stock: int
    image_url: str = ""
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

    # New fields
    price_ranges: list[PriceRange] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    sku_images: dict[str, str] = field(default_factory=dict)  # option_value -> image_url
    video_url: str = ""
    shop_url: str = ""
    shop_location: str = ""
    shop_ratings: dict[str, str] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    origin_price: float = 0.0

    raw_sku_data: Any = field(default=None, repr=False)
    raw_init_data: Any = field(default=None, repr=False)
