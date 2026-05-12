"""分布式锁（基于 Redis SET NX EX）

设计要点：
- async context manager 语义，acquire 失败时 __aenter__ 抛 LockAcquireError
- 释放采用 Lua 脚本：GET 一致才 DEL，避免误删别人持有的锁
- 后台自动续期协程，进程异常退出时由 Redis TTL 兜底清理
- Redis 不可用时使用 try_acquire() 由调用方决定降级行为
"""
import asyncio
import secrets
from typing import Optional

from redis.asyncio import Redis

from app.logger import get_logger

logger = get_logger(__name__)


# Lua: 仅当 value 一致时才删除，保证释放原子性
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class LockAcquireError(Exception):
    """获取锁失败"""


class DistributedLock:
    """Redis 分布式锁"""

    def __init__(
        self,
        redis: Redis,
        key: str,
        ttl: int = 60,
        renew_interval: Optional[int] = None,
    ):
        self._redis = redis
        self._key = f"lock:{key}"
        self._ttl = ttl
        self._renew_interval = renew_interval or max(ttl // 3, 1)
        self._token = secrets.token_hex(16)
        self._renew_task: Optional[asyncio.Task] = None
        self._acquired: bool = False

    async def try_acquire(self) -> bool:
        """非阻塞抢锁；成功返回 True 并启动续期协程"""
        ok = await self._redis.set(self._key, self._token, nx=True, ex=self._ttl)
        if ok:
            self._acquired = True
            self._renew_task = asyncio.create_task(self._renew_loop())
        return bool(ok)

    async def _renew_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._renew_interval)
                # 仅持有者才续期，避免锁被别人接手后还在续
                renewed = await self._redis.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] "
                    "then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
                    1,
                    self._key,
                    self._token,
                    self._ttl,
                )
                if not renewed:
                    logger.warning(f"锁 {self._key} 续期失败（可能已被释放或抢占）")
                    self._acquired = False
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"锁 {self._key} 续期协程异常: {e}")

    async def release(self) -> None:
        if self._renew_task is not None:
            self._renew_task.cancel()
            try:
                await self._renew_task
            except (asyncio.CancelledError, Exception):
                pass
            self._renew_task = None

        if self._acquired:
            try:
                await self._redis.eval(_RELEASE_SCRIPT, 1, self._key, self._token)
            except Exception as e:
                logger.warning(f"释放锁 {self._key} 失败: {e}")
            self._acquired = False

    async def __aenter__(self) -> "DistributedLock":
        if not await self.try_acquire():
            raise LockAcquireError(f"无法获取锁 {self._key}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.release()

    @property
    def acquired(self) -> bool:
        return self._acquired
