from fastapi import FastAPI, HTTPException, Depends, Query
from typing import List, Optional
from redis import Redis
from redis.exceptions import ConnectionError
from .models import Device, ReserveRequest, ReleaseRequest, Heartbeat
from .storage import DeviceStore
from .appium_controller import start_appium_session, stop_appium_session
from .config import REDIS_URL
from .appium_pool import AppiumServerPool

app = FastAPI(title="Mobile Device Manager (Redis)")

def get_redis() -> Redis:
    try:
        r = Redis.from_url(REDIS_URL, decode_responses=False)
        r.ping()
        return r
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {e}")

def get_store(r: Redis = Depends(get_redis)) -> DeviceStore:
    return DeviceStore(r)

def get_appium_pool(r: Redis = Depends(get_redis)) -> AppiumServerPool:
    try:
        return AppiumServerPool(r)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/devices/register")
def register_device(device: Device, store: DeviceStore = Depends(get_store)):
    store.register(device)
    return {"message": f"Device {device.device_id} registered/updated."}

@app.get("/devices", response_model=List[Device])
def list_devices(
    status: Optional[str] = Query(None, pattern="^(available|in_use|offline)$"),
    platform: Optional[str] = Query(None, pattern="^(android|ios)$"),
    store: DeviceStore = Depends(get_store)
):
    devs = store.list(status=status, platform=platform)  # type: ignore
    return devs

@app.get("/devices/{device_id}", response_model=Device)
def get_device(device_id: str, store: DeviceStore = Depends(get_store)):
    d = store.get(device_id)
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    return d

@app.post("/devices/reserve")
def reserve_device(
    req: ReserveRequest,
    store: DeviceStore = Depends(get_store),
    pool: AppiumServerPool = Depends(get_appium_pool),
):
    d = store.get(req.device_id)
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    if d.status != "available":
        raise HTTPException(status_code=409, detail=f"Device is {d.status}")

    if not store.acquire_lock(req.device_id):
        raise HTTPException(status_code=423, detail="Device is being reserved by another process")

    try:
        # Double-check under lock
        d = store.get(req.device_id)
        if not d or d.status != "available":
            raise HTTPException(status_code=409, detail="Device became unavailable")

        # Ensure wdaLocalPort when iOS
        wda_port = d.wda_local_port
        if d.platform == "ios":
            if req.wda_local_port:
                wda_port = req.wda_local_port
                store.set_wda_port_on_device(d.device_id, wda_port)
            elif not wda_port:
                wda_port = store.allocate_wda_port()
                store.set_wda_port_on_device(d.device_id, wda_port)

        try:
            server = pool.acquire()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        try:
            session_id = start_appium_session(
                server,
                d.device_id,
                d.platform,
                d.version,
                wda_local_port=wda_port,
            )
        except Exception as exc:
            pool.release(server)
            raise HTTPException(status_code=502, detail=f"Failed to start Appium session: {exc}") from exc

        store.reserve(d.device_id, session_id, server)
        return {
            "message": f"Device {d.device_id} reserved",
            "session_id": session_id,
            "wdaLocalPort": wda_port,
            "appiumServer": server,
        }
    finally:
        store.release_lock(req.device_id)

@app.post("/devices/{device_id}/release")
def release_device(
    device_id: str,
    body: ReleaseRequest = ReleaseRequest(),
    store: DeviceStore = Depends(get_store),
    pool: AppiumServerPool = Depends(get_appium_pool),
):
    d = store.get(device_id)
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    if d.status != "in_use":
        raise HTTPException(status_code=409, detail="Device is not in use")
    server = d.appium_server
    if d.current_session and server:
        try:
            stop_appium_session(server, d.current_session)
        except Exception:
            pass
    if server:
        pool.release(server)
    store.release(device_id)
    return {"message": f"Device {device_id} released"}

@app.post("/devices/heartbeat")
def heartbeat(hb: Heartbeat, store: DeviceStore = Depends(get_store)):
    d = store.get(hb.device_id)
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    store.heartbeat(hb.device_id)
    return {"message": "ok"}
