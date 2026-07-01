from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class Product:
    title: str
    price: str
    description: Optional[str] = None
    condition: Optional[str] = None
    brand: Optional[str] = None
    characteristics: Dict[str, List[str]] = field(default_factory=dict)
    downloaded_images: List[str] = field(default_factory=list)