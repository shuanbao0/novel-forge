"""Redis 连接池单例

设计要点：
- 模块级私有变量持有唯一 ConnectionPool，跟 database._engine_cache 模式对齐
- init_redis() 在 lifespan startup 调用：连不上就置位 _disabled，业务层走降级
- 失败不抛异常、不阻塞应用启动；Redis 是增强项而非硬依赖
"""
from typing import Optional

import redis.asyncio as redis_async
from redis.asyncio import Redis, ConnectionPool

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

_pool: Optional[ConnectionPool] = None
_client: Optional[Redis] = None
_disabled: bool = False


async def init_redis() -> bool:
    """初始化 Redis 连接池。返回是否可用。"""
    global _pool, _client, _disabled

    if not settings.REDIS_ENABLED:
        logger.info("Redis 已通过 REDIS_ENABLED=False 显式禁用，使用内存降级")
        _disabled = True
        return False

    if not settings.REDIS_URL:
        logger.warning("未配置 REDIS_URL，使用内存降级（仅适合单 worker 部署）")
        _disabled = True
        return False

    try:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
            health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL,
        )
        _client = Redis(connection_pool=_pool)
        await _client.ping()
        _disabled = False
        logger.info("Redis 连接池已初始化")
        return True
    except Exception as e:
        logger.warning(f"Redis 初始化失败，使用内存降级: {e}")
        _disabled = True
        if _client is not None:
            try:
                await _client.aclose()
            except Exception:
                pass
        _client = None
        _pool = None
        return False


async def close_redis() -> None:
    """关闭 Redis 连接池（lifespan shutdown 调用）"""
    global _pool, _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as e:
            logger.warning(f"关闭 Redis 客户端失败: {e}")
    if _pool is not None:
        try:
            await _pool.disconnect(inuse_connections=True)
        except Exception as e:
            logger.warning(f"释放 Redis 连接池失败: {e}")
    _client = None
    _pool = None


def get_redis() -> Optional[Redis]:
    """获取 Redis 客户端；不可用返回 None，调用方需判空"""
    if _disabled:
        return None
    return _client


def is_available() -> bool:
    """Redis 是否可用"""
    return not _disabled and _client is not None
