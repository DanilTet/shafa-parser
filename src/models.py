from dataclasses import dataclass, field

@dataclass
class Product:
    title: str
    price: str
    description: str
    condition: str
    brand: str
    original_url: str = ""
    characteristics: dict = field(default_factory=dict)
    downloaded_images: list = field(default_factory=list)

@dataclass
class SyncItem:
    item_id: str
    url: str
    title: str
    price: str = ""
    status: str = "pending"  # "pending" | "published" | "skipped" | "failed"
    published_at: str | None = None
    error: str | None = None