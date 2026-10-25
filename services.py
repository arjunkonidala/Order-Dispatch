import math
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Driver

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two latitude/longitude points."""
    radius_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(min(1.0, a)))

def lock_nearest_available_driver(db: Session, latitude: float, longitude: float) -> Driver | None:
    # PostgreSQL locks selected driver rows until the surrounding transaction ends.
    # SKIP LOCKED makes concurrent assignments skip drivers another transaction holds.
    drivers = db.scalars(
        select(Driver)
        .where(Driver.available.is_(True))
        .order_by(Driver.id)
        .with_for_update(skip_locked=True)
    ).all()
    if not drivers:
        return None
    return min(drivers, key=lambda d: haversine_km(latitude, longitude, d.latitude, d.longitude))
