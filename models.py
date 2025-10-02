from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

DeviceStatus = Literal["available", "in_use", "offline"]

class Device(BaseModel):
    device_id: str = Field(..., min_length=1)
    platform: Literal["android", "ios"]
    version: str
    location: Optional[str] = None
    status: DeviceStatus = "available"
    current_session: Optional[str] = None
    updated_at: Optional[datetime] = None
    # iOS: ensure per-device WDA port to avoid collisions
    wda_local_port: Optional[int] = None
    appium_server: Optional[str] = None

class ReserveRequest(BaseModel):
    device_id: str
    test_id: str
    # Optional override for iOS WDA port
    wda_local_port: Optional[int] = None

class ReleaseRequest(BaseModel):
    reason: Optional[str] = None

class Heartbeat(BaseModel):
    device_id: str
