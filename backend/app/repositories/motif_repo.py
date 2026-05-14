"""意象去重仓库 - 跟踪每个项目里反复出现的口头禅 / 场景词 / 标志意象

设计目的:
- 用最小存储成本(复用 StoryMemory 表, memory_type='used_motif')实现"已用元素表"
- 在章节生成 PostGen 阶段由 MotifExtractionHook 写入,在下章生成前由
  MotifCoolingDecorator 读出,形成 prompt 闭环反馈

字段映射:
  StoryMemory.content          = motif 字面文本(如 "红榜见"、"消毒水味")
  StoryMemory.story_timeline   = 首次/最近出现的章节序号
  StoryMemory.chapter_id       = 最近出现的章节 id
  StoryMemory.importance_score = 累计出现次数 / 10(直接当计数器读)
  StoryMemory.title            = motif 简称, 用于 to_dict 渲染

Repository 不暴露 ORM 细节, 调用方只看到 list[str]。
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.memory import StoryMemory

logger = get_logger(__name__)


# 每次出现给计数器加多少。importance_score 上限是 1.0,所以 0.1 等价"出现 10 次封顶"。
_USAGE_STEP = 0.1
_USAGE_MAX = 1.0
# 超用阈值: importance_score 达到此值就被纳入"禁用"列表。0.5 ≈ 出现过 5 次。
_OVERUSED_THRESHOLD = 0.5
# 单次读取上限,防止极端项目下注入 prompt 过长。
_MAX_RETURN = 30


class MotifRepository:
    """已用意象存取入口"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def record_batch(
        self,
        *,
        project_id: str,
        chapter_id: str,
        chapter_number: int,
        motifs: List[str],
    ) -> int:
        """记录本章抽取出的若干 motif。

        - 若 motif 在该项目下已存在: importance_score += _USAGE_STEP 并更新 story_timeline
        - 否则插入一条新行, importance_score = _USAGE_STEP

        返回成功记录的条数。
        """
        normalized = _normalize_motifs(motifs)
        if not normalized:
            return 0

        # 一次查询拉出本项目下所有已知 motif(content -> 记录),避免 N+1
        existing_q = await self._db.execute(
            select(StoryMemory).where(
                StoryMemory.project_id == project_id,
                StoryMemory.memory_type == "used_motif",
            )
        )
        existing = {row.content: row for row in existing_q.scalars().all()}

        recorded = 0
        for motif in normalized:
            row = existing.get(motif)
            if row is not None:
                row.importance_score = min(
                    _USAGE_MAX,
                    (row.importance_score or 0.0) + _USAGE_STEP,
                )
                row.story_timeline = chapter_number
                row.chapter_id = chapter_id
            else:
                self._db.add(
                    StoryMemory(
                        id=str(uuid.uuid4()),
                        project_id=project_id,
                        chapter_id=chapter_id,
                        memory_type="used_motif",
                        title=motif[:50],
                        content=motif,
                        importance_score=_USAGE_STEP,
                        story_timeline=chapter_number,
                    )
                )
            recorded += 1
        await self._db.commit()
        return recorded

    async def get_cooling(
        self,
        project_id: str,
        current_chapter: int,
        lookback: int = 3,
    ) -> List[str]:
        """返回最近 lookback 章里出现过、但未达到"超用"阈值的 motif。

        交给 MotifCoolingDecorator 作为"建议本章避免"列表。
        """
        if current_chapter <= 1:
            return []
        lower = max(1, current_chapter - lookback)
        q = await self._db.execute(
            select(StoryMemory.content)
            .where(StoryMemory.project_id == project_id)
            .where(StoryMemory.memory_type == "used_motif")
            .where(StoryMemory.story_timeline >= lower)
            .where(StoryMemory.story_timeline < current_chapter)
            .where(StoryMemory.importance_score < _OVERUSED_THRESHOLD)
            .order_by(StoryMemory.story_timeline.desc())
            .limit(_MAX_RETURN)
        )
        return [c for (c,) in q.all() if c]

    async def get_overused(
        self,
        project_id: str,
        threshold: Optional[int] = None,
    ) -> List[str]:
        """返回累计使用次数 ≥ threshold(默认 5)的 motif。

        交给 MotifCoolingDecorator 作为"本章禁用"列表。
        threshold 参数以"出现次数"传入, 内部转换为 importance_score 比较。
        """
        score_threshold = _OVERUSED_THRESHOLD
        if threshold is not None:
            score_threshold = max(0.0, min(_USAGE_MAX, threshold * _USAGE_STEP))
        q = await self._db.execute(
            select(StoryMemory.content)
            .where(StoryMemory.project_id == project_id)
            .where(StoryMemory.memory_type == "used_motif")
            .where(StoryMemory.importance_score >= score_threshold)
            .order_by(StoryMemory.importance_score.desc())
            .limit(_MAX_RETURN)
        )
        return [c for (c,) in q.all() if c]


def _normalize_motifs(motifs: List[str]) -> List[str]:
    """裁剪长度、去重、剥离引号"""
    seen: set[str] = set()
    out: List[str] = []
    for raw in motifs or []:
        if not isinstance(raw, str):
            continue
        s = raw.strip().strip('"\'「」『』《》[]()').strip()
        if not s or len(s) > 30:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out
