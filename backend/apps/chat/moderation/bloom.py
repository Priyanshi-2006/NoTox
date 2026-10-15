"""
Bloom filter backends for chat moderation Layer 2:
- LocalBloomBackend: In-memory bitarray with double-hashing (Kirsch-Mitzenmacher).
- RedisBloomBackend: RedisBloom using redis.asyncio with raw execute_command("BF.MEXISTS", ...).
"""

import asyncio
import hashlib
import logging
import math
from abc import ABC, abstractmethod
from typing import Iterable, List, Optional, Set

from django.conf import settings

logger = logging.getLogger(__name__)


def calculate_bloom_dimensions(n: int, p: float) -> tuple[int, int]:
    """
    Calculate optimal bit array size m and number of hash functions k.
    Formula:
      m = -n * ln(p) / (ln(2))^2
      k = (m / n) * ln(2)
    For n = 50,000 and p = 0.001: m ~ 718,944 bits (~90 KB) and k ~ 10.
    """
    if n <= 0:
        raise ValueError("Capacity n must be positive.")
    if not (0.0 < p < 1.0):
        raise ValueError("Error rate p must be strictly between 0 and 1.")

    m = int(math.ceil(-(n * math.log(p)) / (math.log(2) ** 2)))
    k = int(round((m / n) * math.log(2)))
    return m, max(1, k)


class BloomBackendError(Exception):
    """Base exception for Bloom filter backend failures."""
    pass


class BaseBloomBackend(ABC):
    """Abstract base class for Bloom filter implementations."""

    @abstractmethod
    async def add(self, item: str) -> None:
        pass

    @abstractmethod
    async def add_many(self, items: Iterable[str]) -> int:
        pass

    @abstractmethod
    async def contains(self, item: str) -> bool:
        pass

    @abstractmethod
    async def contains_any(self, items: Iterable[str]) -> bool:
        pass

    @abstractmethod
    async def clear(self) -> None:
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        pass


class LocalBloomBackend(BaseBloomBackend):
    """
    In-memory Bloom filter implementation.
    Uses double-hashing (Kirsch-Mitzenmacher) with SHA-256 to generate k bit positions.
    """

    def __init__(
        self,
        capacity: Optional[int] = None,
        error_rate: Optional[float] = None,
    ):
        self.capacity = (
            capacity
            if capacity is not None
            else getattr(settings, "BLOOM_CAPACITY", 50000)
        )
        self.error_rate = (
            error_rate
            if error_rate is not None
            else getattr(settings, "BLOOM_ERROR_RATE", 0.001)
        )
        self.m, self.k = calculate_bloom_dimensions(self.capacity, self.error_rate)
        self._num_bytes = (self.m + 7) // 8
        self._bitarray = bytearray(self._num_bytes)
        self._count = 0
        self._lock = asyncio.Lock()

    @property
    def item_count(self) -> int:
        return self._count

    def _get_hash_indices(self, item: str) -> List[int]:
        """
        Compute k bit indices using 128-bit SHA-256 slices:
        g_i(x) = (h1 + i * h2) % m
        """
        digest = hashlib.sha256(item.encode("utf-8")).digest()
        h1 = int.from_bytes(digest[:8], "big")
        h2 = int.from_bytes(digest[8:16], "big")
        if h2 == 0:
            h2 = 1

        indices: List[int] = []
        for i in range(self.k):
            idx = (h1 + i * h2) % self.m
            indices.append(idx)
        return indices

    def _sync_add(self, item: str) -> None:
        if not item:
            return
        indices = self._get_hash_indices(item)
        for idx in indices:
            byte_idx = idx // 8
            bit_idx = idx % 8
            self._bitarray[byte_idx] |= (1 << bit_idx)
        self._count += 1

    def _sync_contains(self, item: str) -> bool:
        if not item:
            return False
        indices = self._get_hash_indices(item)
        for idx in indices:
            byte_idx = idx // 8
            bit_idx = idx % 8
            if not (self._bitarray[byte_idx] & (1 << bit_idx)):
                return False
        return True

    async def add(self, item: str) -> None:
        async with self._lock:
            self._sync_add(item)

    async def add_many(self, items: Iterable[str]) -> int:
        count = 0
        async with self._lock:
            for item in items:
                if item:
                    self._sync_add(item)
                    count += 1
        return count

    async def contains(self, item: str) -> bool:
        return self._sync_contains(item)

    async def contains_any(self, items: Iterable[str]) -> bool:
        for item in items:
            if self._sync_contains(item):
                return True
        return False

    async def clear(self) -> None:
        async with self._lock:
            self._bitarray = bytearray(self._num_bytes)
            self._count = 0

    async def is_healthy(self) -> bool:
        return True


class RedisBloomBackend(BaseBloomBackend):
    """
    RedisBloom backend using redis.asyncio with raw execute_command("BF.MEXISTS", ...).
    Runs one round trip per message across all candidate keys.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
        key: Optional[str] = None,
        capacity: Optional[int] = None,
        error_rate: Optional[float] = None,
        timeout_ms: Optional[int] = None,
    ):
        self.host = host or getattr(settings, "REDIS_HOST", "localhost")
        self.port = port or getattr(settings, "REDIS_PORT", 6379)
        self.password = password or getattr(settings, "REDIS_PASSWORD", "") or None
        self.key = key or getattr(settings, "BLOOM_REDIS_KEY", "notox:bloom:toxic")
        self.capacity = (
            capacity
            if capacity is not None
            else getattr(settings, "BLOOM_CAPACITY", 50000)
        )
        self.error_rate = (
            error_rate
            if error_rate is not None
            else getattr(settings, "BLOOM_ERROR_RATE", 0.001)
        )
        self.timeout_ms = (
            timeout_ms
            if timeout_ms is not None
            else getattr(settings, "BLOOM_TIMEOUT_MS", 20)
        )
        self._client = None

    def get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis
            self._client = aioredis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                decode_responses=False,
                socket_timeout=self.timeout_ms / 1000.0,
                socket_connect_timeout=self.timeout_ms / 1000.0,
            )
        return self._client

    async def probe(self) -> bool:
        """
        Probe whether Redis is alive and RedisBloom module is available.
        Executes BF.EXISTS on a dummy key.
        """
        try:
            client = self.get_client()
            await asyncio.wait_for(
                client.execute_command("BF.EXISTS", "probe_test_filter", "probe"),
                timeout=self.timeout_ms / 1000.0,
            )
            return True
        except Exception as exc:
            logger.debug("RedisBloom capability probe failed: %s", exc)
            return False

    async def is_healthy(self) -> bool:
        return await self.probe()

    async def reserve(self) -> bool:
        """
        Reserve the Bloom filter in Redis with capacity and error rate.
        Idempotent: ignores errors if filter already exists.
        """
        client = self.get_client()
        try:
            await client.execute_command(
                "BF.RESERVE",
                self.key,
                str(self.error_rate),
                str(self.capacity),
            )
            return True
        except Exception as exc:
            msg = str(exc).lower()
            if "item exists" in msg or "already exists" in msg:
                return True
            raise BloomBackendError(f"Failed to reserve Redis Bloom filter: {exc}") from exc

    async def add(self, item: str) -> None:
        if not item:
            return
        await self.add_many([item])

    async def add_many(self, items: Iterable[str]) -> int:
        item_list = [i for i in items if i]
        if not item_list:
            return 0

        client = self.get_client()
        batch_size = 1000
        total_added = 0

        for i in range(0, len(item_list), batch_size):
            batch = item_list[i : i + batch_size]
            try:
                res = await client.execute_command("BF.MADD", self.key, *batch)
                total_added += sum(1 for r in res if r)
            except Exception as exc:
                raise BloomBackendError(f"RedisBloom BF.MADD error: {exc}") from exc

        return total_added

    async def contains(self, item: str) -> bool:
        if not item:
            return False
        return await self.contains_any([item])

    async def contains_any(self, items: Iterable[str]) -> bool:
        item_list = [i for i in items if i]
        if not item_list:
            return False

        client = self.get_client()
        timeout_sec = self.timeout_ms / 1000.0

        try:
            # Single round trip per message across all candidate keys
            res = await asyncio.wait_for(
                client.execute_command("BF.MEXISTS", self.key, *item_list),
                timeout=timeout_sec,
            )
            return any(r == 1 or r == b"1" or r is True for r in res)
        except Exception as exc:
            raise BloomBackendError(f"RedisBloom query failed or timed out: {exc}") from exc

    async def clear(self) -> None:
        client = self.get_client()
        try:
            await client.delete(self.key)
        except Exception as exc:
            raise BloomBackendError(f"Failed to clear Redis Bloom filter: {exc}") from exc

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


_default_bloom_backend: Optional[BaseBloomBackend] = None


def get_bloom_backend(backend_type: Optional[str] = None) -> BaseBloomBackend:
    global _default_bloom_backend
    target_backend = (
        backend_type or getattr(settings, "BLOOM_BACKEND", "local")
    ).lower()

    if target_backend == "redis":
        return RedisBloomBackend()

    # Local is default singleton
    if _default_bloom_backend is None or not isinstance(
        _default_bloom_backend, LocalBloomBackend
    ):
        _default_bloom_backend = LocalBloomBackend()
    return _default_bloom_backend


def reset_bloom_backend() -> None:
    global _default_bloom_backend
    _default_bloom_backend = None
