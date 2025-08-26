from dataclasses import dataclass, asdict
from typing import List, Dict
import uuid
from datetime import datetime

@dataclass
class Shop:
    id: int
    name: str
    address: str
    contact: str
    shopkeeper_id: int

    def to_dict(self) -> Dict:
        return asdict(self)

@dataclass
class Item:
    id: int
    name: str
    price: float
    stock_quantity: int
    description: str
    shopid: int
    imageurl: str

    def to_dict(self) -> Dict:
        # Return camelCase keys expected by Kotlin
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "stockQuantity": self.stock_quantity,
            "description": self.description,
            "shopid": self.shopid,
            "imageUrl": self.imageurl
        }



class Order:
    def __init__(self, order_id, shop_id, customer, items, total, status):
        self.order_id = order_id
        self.order_uuid = str(uuid.uuid4())
        self.shop_id = shop_id
        self.customer = customer
        self.items = items
        self.total = total
        self.status = status
        self.created_at = datetime.utcnow().isoformat()
        self.updated_at = ""  # ✅ Add this field initially blank

    def to_dict(self, get_item_by_id_fn):
        from storage import shops

        shop_name = next((s.name for s in shops if s.id == self.shop_id), "Unknown Shop")

        return {
            "order_id": self.order_id,
            "order_uuid": self.order_uuid,
            "shop_id": self.shop_id,
            "shop_name": shop_name,
            "customer": self.customer,
            "items": [
                {
                    "item": get_item_by_id_fn(i["item_id"]).to_dict(),
                    "quantity": i["quantity"]
                } for i in self.items
            ],
            "total": self.total,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at  # ✅ Include in dict
        }

