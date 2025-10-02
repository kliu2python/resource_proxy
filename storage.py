import time
from typing import List, Optional, Dict, Any
from redis import Redis
from .models import Device, DeviceStatus
from .config import RESERVE_LOCK_TTL, HEARTBEAT_TTL, WDA_PORT_START, WDA_PORT_END

DEVICE_KEY = "device:{id}"
STATUS_IDX = "idx:status:{status}"
PLATFORM_IDX = "idx:platform:{platform}"
LOCK_KEY = "lock:device:{id}"
HB_KEY = "hb:device:{id}"

# Track used iOS WDA ports globally
WDA_USED_SET = "used:wdalocal"
WDA_POOL_LOCK = "lock:wdapool"

def _device_to_hash(d: Device) -> Dict[str, Any]:
    return {
        "device_id": d.device_id,
        "platform": d.platform,
        "version": d.version,
        "location": d.location or "",
        "status": d.status,
        "current_session": d.current_session or "",
        "wda_local_port": str(d.wda_local_port or ""),
        "updated_at": str(int(time.time()))
    }

def _hash_to_device(h: Dict[str, Any]) -> Device:
    if not h:
        raise KeyError("device not found")
    wda = h.get("wda_local_port")
    try:
        wda = int(wda) if (wda and str(wda).strip()) else None
    except Exception:
        wda = None
    return Device(
        device_id=h.get("device_id"),
        platform=h.get("platform"),
        version=h.get("version"),
        location=h.get("location") or None,
        status=h.get("status"),  # type: ignore
        current_session=h.get("current_session") or None,
        updated_at=None,
        wda_local_port=wda
    )

class DeviceStore:
    def __init__(self, r: Redis):
        self.r = r

    # ---- Registration / Upsert ----
    def register(self, d: Device) -> None:
        key = DEVICE_KEY.format(id=d.device_id)
        h = self.r.hgetall(key)
        old_status = h.get(b"status", b"").decode() if h else None

        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping=_device_to_hash(d))
        pipe.sadd(PLATFORM_IDX.format(platform=d.platform), d.device_id)
        if old_status and old_status != d.status:
            pipe.srem(STATUS_IDX.format(status=old_status), d.device_id)
        pipe.sadd(STATUS_IDX.format(status=d.status), d.device_id)

        # If iOS device is registered with a fixed WDA port, mark it used
        if d.platform == "ios" and d.wda_local_port:
            pipe.sadd(WDA_USED_SET, d.wda_local_port)

        pipe.execute()

    def get(self, device_id: str) -> Optional[Device]:
        key = DEVICE_KEY.format(id=device_id)
        raw = self.r.hgetall(key)
        if not raw:
            return None
        h = {k.decode(): v.decode() for k, v in raw.items()}
        dev = _hash_to_device(h)
        # if heartbeat missing and status says available, surface offline to caller
        if self.r.ttl(HB_KEY.format(id=device_id)) == -2 and dev.status == "available":
            dev.status = "offline"
        return dev

    def list(self,
             status: Optional[DeviceStatus] = None,
             platform: Optional[str] = None) -> List[Device]:
        ids: Optional[set[str]] = None
        if status:
            ids = set(x.decode() for x in self.r.smembers(STATUS_IDX.format(status=status)))
        if platform:
            pset = set(x.decode() for x in self.r.smembers(PLATFORM_IDX.format(platform=platform)))
            ids = pset if ids is None else (ids & pset)
        if ids is None:
            ids = set()
            for st in ["available", "in_use", "offline"]:
                ids |= set(x.decode() for x in self.r.smembers(STATUS_IDX.format(status=st)))
        devices: List[Device] = []
        for did in sorted(ids):
            d = self.get(did)
            if d:
                devices.append(d)
        return devices

    def _update_status(self, device_id: str, new_status: DeviceStatus) -> None:
        key = DEVICE_KEY.format(id=device_id)
        h = self.r.hgetall(key)
        if not h:
            raise KeyError("device not found")
        old_status = h.get(b"status", b"").decode()
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping={"status": new_status, "updated_at": str(int(time.time()))})
        if old_status and old_status != new_status:
            pipe.srem(STATUS_IDX.format(status=old_status), device_id)
            pipe.sadd(STATUS_IDX.format(status=new_status), device_id)
        pipe.execute()

    # ---- Locking ----
    def acquire_lock(self, device_id: str) -> bool:
        return self.r.set(LOCK_KEY.format(id=device_id), "1", nx=True, ex=RESERVE_LOCK_TTL) is True

    def release_lock(self, device_id: str) -> None:
        self.r.delete(LOCK_KEY.format(id=device_id))

    # ---- Reserve / Release ----
    def reserve(self, device_id: str, session_id: str) -> None:
        key = DEVICE_KEY.format(id=device_id)
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping={
            "status": "in_use",
            "current_session": session_id,
            "updated_at": str(int(time.time()))
        })
        pipe.srem(STATUS_IDX.format(status="available"), device_id)
        pipe.sadd(STATUS_IDX.format(status="in_use"), device_id)
        pipe.execute()

    def release(self, device_id: str) -> None:
        key = DEVICE_KEY.format(id=device_id)
        wda_port = self.r.hget(key, "wda_local_port")
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping={
            "status": "available",
            "current_session": "",
            "updated_at": str(int(time.time()))
        })
        pipe.srem(STATUS_IDX.format(status="in_use"), device_id)
        pipe.sadd(STATUS_IDX.format(status="available"), device_id)
        # free global WDA used marker (device keeps port assignment, but free marker)
        if wda_port and wda_port.decode().strip():
            try:
                pipe.srem(WDA_USED_SET, int(wda_port))
            except Exception:
                pass
        pipe.execute()

    # ---- Heartbeat ----
    def heartbeat(self, device_id: str) -> None:
        self.r.set(HB_KEY.format(id=device_id), "1", ex=HEARTBEAT_TTL)
        d = self.get(device_id)
        if d and d.status == "offline":
            self._update_status(device_id, "available")

    # ---- WDA Ports ----
    def _alloc_wda_port_locked(self) -> Optional[int]:
        used = set(int(x.decode()) for x in self.r.smembers(WDA_USED_SET))
        for p in range(WDA_PORT_START, WDA_PORT_END + 1):
            if p not in used:
                self.r.sadd(WDA_USED_SET, p)
                return p
        return None

    def allocate_wda_port(self) -> int:
        # coarse pool lock to avoid contention
        if self.r.set(WDA_POOL_LOCK, "1", nx=True, ex=5):
            try:
                port = self._alloc_wda_port_locked()
                if port is None:
                    raise RuntimeError("No free wdaLocalPort in configured range")
                return port
            finally:
                self.r.delete(WDA_POOL_LOCK)
        else:
            time.sleep(0.1)
            return self.allocate_wda_port()

    def set_wda_port_on_device(self, device_id: str, port: int) -> None:
        key = DEVICE_KEY.format(id=device_id)
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping={"wda_local_port": str(port), "updated_at": str(int(time.time()))})
        pipe.sadd(WDA_USED_SET, port)
        pipe.execute()
