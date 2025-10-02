from __future__ import annotations

from typing import Iterable, Sequence

from redis import Redis

from .config import APPIUM_SERVERS

AVAILABLE_SET = "appium:servers:available"
IN_USE_SET = "appium:servers:in_use"


def _normalise(server: str) -> str:
    return server.rstrip("/")


class AppiumServerPool:
    """Redis backed pool used to acquire and release Appium servers."""

    def __init__(self, redis: Redis, servers: Sequence[str] | None = None):
        self.redis = redis
        self.servers = [_normalise(s) for s in (servers or APPIUM_SERVERS) if s]
        self._server_set = set(self.servers)
        if not self.servers:
            raise RuntimeError("No Appium servers configured")
        self._ensure_servers_registered()

    def _ensure_servers_registered(self) -> None:
        available = set(self.redis.smembers(AVAILABLE_SET))
        in_use = set(self.redis.smembers(IN_USE_SET))
        existing = available | in_use
        desired = {s.encode() for s in self.servers}

        # Remove stale servers that are no longer configured
        stale_available = available - desired
        if stale_available:
            self.redis.srem(AVAILABLE_SET, *stale_available)

        missing = desired - existing
        if missing:
            self.redis.sadd(AVAILABLE_SET, *missing)

    def acquire(self) -> str:
        server = self.redis.spop(AVAILABLE_SET)
        if not server:
            raise RuntimeError("No available Appium servers")
        server_str = _normalise(server.decode())
        # Track the in-use set for observability and rebalancing on release
        self.redis.sadd(IN_USE_SET, server_str)
        return server_str

    def release(self, server: str) -> None:
        normalised = _normalise(server)
        pipe = self.redis.pipeline(transaction=True)
        pipe.srem(IN_USE_SET, normalised)
        if normalised in self._server_set:
            pipe.sadd(AVAILABLE_SET, normalised)
        pipe.execute()

    def all_servers(self) -> Iterable[str]:
        for server in self.servers:
            yield server
