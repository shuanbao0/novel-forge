"""OAuth state 仓库（替代 auth.py 中的 _state_storage 内存 dict）"""
import secrets

from app.infra.kv_store import KVStore


class OAuthStateRepository:
    """OAuth2 state 一次性凭证存取

    设计：
    - issue() 生成 state 并写入存储，自动 10 分钟过期
    - consume() 一次性消费：存在即删除返回 True，避免重放
    """

    KEY_PREFIX = "oauth:state:"
    TTL_SECONDS = 600

    def __init__(self, kv: KVStore):
        self._kv = kv

    def _key(self, state: str) -> str:
        return f"{self.KEY_PREFIX}{state}"

    async def issue(self, state: str) -> None:
        """登记一个外部生成的 state"""
        await self._kv.set(self._key(state), "1", ex=self.TTL_SECONDS)

    async def generate_and_issue(self) -> str:
        """生成并登记 state，返回 state 值"""
        state = secrets.token_urlsafe(32)
        await self.issue(state)
        return state

    async def consume(self, state: str) -> bool:
        """一次性消费 state；存在则删除并返回 True"""
        key = self._key(state)
        if await self._kv.exists(key):
            await self._kv.delete(key)
            return True
        return False
