import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
APPIUM_SERVER = os.getenv("APPIUM_SERVER", "http://localhost:4723/wd/hub")

def _parse_server_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    servers: list[str] = []
    for chunk in raw.split(","):
        candidate = chunk.strip()
        if not candidate:
            continue
        # Normalise trailing slashes so pool entries match consistently
        servers.append(candidate.rstrip("/"))
    return servers

# Comma separated list of Appium servers, falling back to single APPIUM_SERVER
APPIUM_SERVERS = _parse_server_list(os.getenv("APPIUM_SERVERS"))
if not APPIUM_SERVERS:
    APPIUM_SERVERS = _parse_server_list(os.getenv("APPIUM_SERVER")) or [
        "http://localhost:4723/wd/hub"
    ]

RESERVE_LOCK_TTL = int(os.getenv("RESERVE_LOCK_TTL", "60"))
HEARTBEAT_TTL = int(os.getenv("HEARTBEAT_TTL", "120"))

# iOS WDA port allocation range
WDA_PORT_START = int(os.getenv("WDA_PORT_START", "8100"))
WDA_PORT_END   = int(os.getenv("WDA_PORT_END",   "8199"))
