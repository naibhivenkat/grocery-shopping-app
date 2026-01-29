from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime


def now_iso() -> str:
    return datetime.utcnow().isoformat()


@dataclass
class ServiceProvider:
    uid: str
    role: str  # provider or requester
    name: str
    mobile: str
    email: str
    password_hash: str
    service_category_id: str
    location: str
    bank: Dict[str, Any]
    working_days: List[str]
    working_hours: Dict[str, str]  # {"from":"09:00","to":"18:00"}
    slot_size: int  # 15/30/60
    blocked_until: Optional[str] = None
    cancel_count: int = 0
    created_at: str = now_iso()

    def to_dict(self):
        return asdict(self)


@dataclass
class ProviderService:
    id: str
    provider_id: str
    service_category_id: str
    title: str
    description: str
    fixed_price: float
    pricing_unit: str  # fixed / per_hour / per_minute / per_day
    created_at: str = now_iso()

    def to_dict(self):
        return asdict(self)


@dataclass
class Booking:
    id: str
    provider_id: str
    requester_id: str
    service_id: str
    slot_date: str  # YYYY-MM-DD
    slot_time: str  # HH:mm
    status: str  # incoming/accepted/rejected/started/completed/cancelled
    reject_reason: Optional[str] = None
    total_cost: float = 0.0
    commission: float = 0.0
    discount: float = 0.0
    created_at: str = now_iso()

    def to_dict(self):
        return asdict(self)
