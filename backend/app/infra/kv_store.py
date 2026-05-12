"""KV 存储抽象（Strategy 模式）

业务层只依赖 KVStore 接口，不直接 import redis。
Redis 可用时用 RedisKVStore，否则透明降级到 InMemoryKVStore（带惰性 TTL 清理）。
"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple

from app.infra.redis_client import get_redis
from app.logger import get_logger

logger = get_logger(__name__)


class KVStore(ABC):
    """KV 存储接口。只暴露当前业务实际用到的方法。"""

    @abstractmethod
    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> Optional[str]: ...

    @abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def incr(self, key: str, ex: Optional[int] = None) -> int: ...


class RedisKVStore(KVStore):
    """Redis 实现"""

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        client = get_redis()
        await client.set(key, value, ex=ex)

    async def get(self, key: str) -> Optional[str]:
        client = get_redis()
        return await client.get(key)

    async def delete(self, key: str) -> bool:
        client = get_redis()
        return bool(await client.delete(key))

    async def exists(self, key: str) -> bool:
        client = get_redis()
        return bool(await client.exists(key))

    async def incr(self, key: str, ex: Optional[int] = None) -> int:
        client = get_redis()
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            if ex is not None:
                pipe.expire(key, ex)
            results = await pipe.execute()
        return int(results[0])


class InMemoryKVStore(KVStore):
    """进程内降级实现：dict + 惰性 TTL 删除 + asyncio.Lock 串行化"""

    def __init__(self) -> None:
        self._data: Dict[str, Tuple[str, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, expires_at: Optional[float]) -> bool:
        return expires_at is not None and expires_at <= time.time()

    async def _purge_if_expired(self, key: str) -> None:
        item = self._data.get(key)
        if item and self._is_expired(item[1]):
            self._data.pop(key, None)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        async with self._lock:
            expires_at = time.time() + ex if ex is not None else None
            self._data[key] = (value, expires_at)

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            await self._purge_if_expired(key)
            item = self._data.get(key)
            return item[0] if item else None

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._data.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        async with self._lock:
            await self._purge_if_expired(key)
            return key in self._data

    async def incr(self, key: str, ex: Optional[int] = None) -> int:
        async with self._lock:
            await self._purge_if_expired(key)
            item = self._data.get(key)
            current = int(item[0]) if item else 0
            new_val = current + 1
            expires_at = item[1] if item else (time.time() + ex if ex is not None else None)
            if item is None and ex is not None:
                expires_at = time.time() + ex
            self._data[key] = (str(new_val), expires_at)
            return new_val


_redis_store = RedisKVStore()
_memory_store = InMemoryKVStore()


def get_kv_store() -> KVStore:
    """工厂：Redis 可用时返回 RedisKVStore，否则返回进程内降级实现"""
    from app.infra.redis_client import is_available
    return _redis_store if is_available() else _memory_store
