"""邮箱验证码仓库（替代 auth.py 中的 _email_verification_storage 内存 dict）"""
import json
from dataclasses import dataclass, asdict
from typing import Optional

from app.infra.kv_store import KVStore


@dataclass
class VerificationRecord:
    """单条验证码记录"""
    code: str
    expires_at: int       # unix 秒
    last_sent_at: int     # unix 秒
    attempts: int = 0


@dataclass
class VerificationLookup:
    """业务层一次取出的视图：记录本身 + 是否已过期"""
    record: VerificationRecord
    expired: bool


class EmailVerificationRepository:
    """邮箱验证码存取

    设计：
    - key 由 (scene, email) 组成，email 由调用方先 normalize
    - 存储采用 JSON 序列化，TTL 由调用方传入（来自系统设置可热更新）
    - increment_attempts 自动 +1 并写回，超过上限由调用方负责删除
    """

    KEY_PREFIX = "email:verify:"

    def __init__(self, kv: KVStore):
        self._kv = kv

    def _key(self, scene: str, email: str) -> str:
        return f"{self.KEY_PREFIX}{scene}:{email}"

    async def save(
        self,
        scene: str,
        email: str,
        record: VerificationRecord,
        ttl_seconds: int,
    ) -> None:
        await self._kv.set(self._key(scene, email), json.dumps(asdict(record)), ex=ttl_seconds)

    async def get(self, scene: str, email: str, now_ts: int) -> Optional[VerificationLookup]:
        """获取验证码记录；不存在返回 None，过期则返回 expired=True 的视图"""
        raw = await self._kv.get(self._key(scene, email))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            record = VerificationRecord(**data)
        except (json.JSONDecodeError, TypeError):
            await self.delete(scene, email)
            return None
        expired = record.expires_at < now_ts
        return VerificationLookup(record=record, expired=expired)

    async def delete(self, scene: str, email: str) -> None:
        await self._kv.delete(self._key(scene, email))

    async def increment_attempts(
        self,
        scene: str,
        email: str,
        record: VerificationRecord,
        ttl_seconds: int,
    ) -> int:
        """attempts +1 并写回，返回新值"""
        record.attempts += 1
        await self.save(scene, email, record, ttl_seconds)
        return record.attempts
