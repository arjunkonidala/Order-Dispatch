from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Driver, IdempotencyRecord, Order
from .schemas import (AvailabilityUpdate, DriverCreate, DriverLocationUpdate, DriverOut,
                      OrderCreate, OrderOut, OrderPage, StatusUpdate)
from .services import lock_nearest_available_driver

ALLOWED_TRANSITIONS = {
    "CREATED": {"CANCELLED"},
    "ASSIGNED": {"PICKED_UP", "CANCELLED"},
    "PICKED_UP": {"DELIVERED"},
    "DELIVERED": set(),
    "CANCELLED": set(),
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Convenient for this starter project. For production, use Alembic migrations.
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Order Dispatch API", version="1.0.0", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/drivers", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db)):
    driver = Driver(**payload.model_dump())
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver

@app.get("/drivers", response_model=list[DriverOut])
def list_drivers(db: Session = Depends(get_db), available: bool | None = None):
    stmt = select(Driver).order_by(Driver.id)
    if available is not None:
        stmt = stmt.where(Driver.available.is_(available))
    return db.scalars(stmt).all()

@app.patch("/drivers/{driver_id}/location", response_model=DriverOut)
def update_driver_location(driver_id: int, payload: DriverLocationUpdate, db: Session = Depends(get_db)):
    driver = db.get(Driver, driver_id)
    if not driver:
        raise HTTPException(404, "Driver not found")
    driver.latitude, driver.longitude = payload.latitude, payload.longitude
    db.commit(); db.refresh(driver)
    return driver

@app.patch("/drivers/{driver_id}/availability", response_model=DriverOut)
def update_driver_availability(driver_id: int, payload: AvailabilityUpdate, db: Session = Depends(get_db)):
    driver = db.scalar(select(Driver).where(Driver.id == driver_id).with_for_update())
    if not driver:
        raise HTTPException(404, "Driver not found")
    if payload.available and db.scalar(select(Order.id).where(Order.driver_id == driver_id, Order.status.in_(["ASSIGNED", "PICKED_UP"])).limit(1)):
        raise HTTPException(409, "Driver has an active order and cannot be marked available")
    driver.available = payload.available
    db.commit(); db.refresh(driver)
    return driver

@app.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, response: Response,
                 idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
                 db: Session = Depends(get_db)):
    # Serialize requests using the same key. A unique PK is the final safety net.
    existing = db.get(IdempotencyRecord, idempotency_key)
    if existing:
        order = db.get(Order, existing.order_id)
        response.status_code = status.HTTP_200_OK
        return order
    try:
        order = Order(**payload.model_dump(), status="CREATED")
        db.add(order)
        db.flush()  # allocate order ID before inserting the idempotency record
        driver = lock_nearest_available_driver(db, payload.pickup_latitude, payload.pickup_longitude)
        if driver:
            driver.available = False
            order.driver_id = driver.id
            order.status = "ASSIGNED"
        db.add(IdempotencyRecord(key=idempotency_key, order_id=order.id))
        db.commit()
        db.refresh(order)
        return order
    except IntegrityError:
        db.rollback()
        existing = db.get(IdempotencyRecord, idempotency_key)
        if existing:
            response.status_code = status.HTTP_200_OK
            return db.get(Order, existing.order_id)
        raise HTTPException(409, "Could not create order due to a database conflict")
    except Exception:
        db.rollback()
        raise

@app.get("/orders", response_model=OrderPage)
def list_orders(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Order)) or 0
    items = db.scalars(select(Order).order_by(Order.created_at.desc(), Order.id.desc())
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return OrderPage(items=items, page=page, page_size=page_size, total=total)

@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order

@app.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_order_status(order_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    target = payload.status.upper()
    if target not in ALLOWED_TRANSITIONS:
        raise HTTPException(422, "Unknown order status")
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, "Order not found")
    if target not in ALLOWED_TRANSITIONS[order.status]:
        raise HTTPException(409, f"Invalid transition: {order.status} -> {target}")
    order.status = target
    if target == "CANCELLED" and order.driver_id is not None:
        driver = db.scalar(select(Driver).where(Driver.id == order.driver_id).with_for_update())
        if driver:
            driver.available = True
        order.driver_id = None
    db.commit(); db.refresh(order)
    return order

@app.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: int, db: Session = Depends(get_db)):
    return update_order_status(order_id, StatusUpdate(status="CANCELLED"), db)
