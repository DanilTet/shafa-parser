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