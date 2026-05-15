"""事实台账仓储 - 复用 StoryMemory 表, 零 alembic 迁移

存储约定:
  StoryMemory.memory_type   = 'fact_ledger'
  StoryMemory.content       = FactLedger.to_json() 序列化后的整个台账
  StoryMemory.story_timeline= last_chapter_number (供调试用)
  StoryMemory.chapter_id    = None  ← 关键: 台账是项目级的, 不归属任何章节;
                              若指向某章, 该章被 DELETE 时 ON CASCADE 会把整个
                              项目台账抹掉. 同理, _reset_chapter_for_rewrite 按
                              chapter_id 批删 StoryMemory 也会误伤(代码侧已加
                              memory_type 排除, 这里是双重保险).

每个 project 只保留一行, save() 走 upsert 语义.
与 MotifRepository 同样的复用策略, 见 repositories/motif_repo.py.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.memory import StoryMemory
from app.services.fact_ledger import FactLedger

logger = get_logger(__name__)


# 项目级 StoryMemory 类型 - 这些行不归属任何单章, 不应在"按章节清理"
# (reset / re-analyze / delete-chapter-memories) 路径里被一锅端删除.
# 任何按 chapter_id 的删除都应该 NOT IN 这个集合.
# 维护规范: 新增项目级 memory_type 时务必加进来.
PROJECT_SCOPED_MEMORY_TYPES: tuple[str, ...] = (
    "fact_ledger",   # FactLedgerRepository - 项目级事实台账(数值/身份)
    "used_motif",    # MotifRepository      - 项目级意象累积计数器
)


class FactLedgerRepository:
    MEMORY_TYPE = "fact_ledger"

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get(self, project_id: str) -> FactLedger:
        """加载该 project 的台账; 不存在时返回空对象, 调用方无需判空."""
        row = await self._db.execute(
            select(StoryMemory)
            .where(StoryMemory.project_id == project_id)
            .where(StoryMemory.memory_type == self.MEMORY_TYPE)
            .limit(1)
        )
        rec: Optional[StoryMemory] = row.scalar_one_or_none()
        if rec is None:
            return FactLedger(project_id=project_id)
        return FactLedger.from_json(project_id, rec.content)

    async def save(
        self,
        ledger: FactLedger,
        *,
        chapter_id: Optional[str] = None,  # 兼容旧调用方; 实际不再持久化, 见上方文档
    ) -> None:
        """upsert 台账. chapter_id 形参保留是为了兼容已有调用方, 实际写库时
        强制 chapter_id=None, 避免章节删除 / 重置引起的级联清除."""
        row = await self._db.execute(
            select(StoryMemory)
            .where(StoryMemory.project_id == ledger.project_id)
            .where(StoryMemory.memory_type == self.MEMORY_TYPE)
            .limit(1)
        )
        rec: Optional[StoryMemory] = row.scalar_one_or_none()
        payload = ledger.to_json()
        if rec is None:
            self._db.add(StoryMemory(
                id=str(uuid.uuid4()),
                project_id=ledger.project_id,
                chapter_id=None,  # 项目级, 不绑章节
                memory_type=self.MEMORY_TYPE,
                title="事实台账",
                content=payload,
                importance_score=1.0,
                story_timeline=ledger.last_chapter_number,
            ))
        else:
            rec.content = payload
            rec.story_timeline = ledger.last_chapter_number
            # 显式置空, 防止历史数据残留的 chapter_id 在 reset 时被命中
            rec.chapter_id = None
        await self._db.commit()
