from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class DriverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

class DriverLocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

class AvailabilityUpdate(BaseModel):
    available: bool

class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    latitude: float
    longitude: float
    available: bool
    created_at: datetime

class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    pickup_latitude: float = Field(ge=-90, le=90)
    pickup_longitude: float = Field(ge=-180, le=180)
    dropoff_latitude: float = Field(ge=-90, le=90)
    dropoff_longitude: float = Field(ge=-180, le=180)

class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_name: str
    pickup_latitude: float
    pickup_longitude: float
    dropoff_latitude: float
    dropoff_longitude: float
    status: str
    driver_id: int | None
    created_at: datetime

class OrderPage(BaseModel):
    items: list[OrderOut]
    page: int
    page_size: int
    total: int

class StatusUpdate(BaseModel):
    status: str
