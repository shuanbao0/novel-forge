"""统一查询服务 - 借鉴 webnovel-writer /webnovel-query

跨多个实体类型的关键字搜索,合并结果按类型分组返回。
- character: 角色
- foreshadow: 伏笔
- memory: 剧情记忆
- review: 审稿意见
- outline: 大纲
- chapter: 章节(标题/正文)
- commit: 章节快照

实现策略:并行执行 SELECT ... ILIKE '%q%',然后合并。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger

logger = get_logger(__name__)


# 支持的实体类型
SUPPORTED_TYPES = ("character", "foreshadow", "memory", "review", "outline", "chapter", "commit")


@dataclass
class SearchHit:
    type: str
    id: str
    title: str
    snippet: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    query: str
    project_id: str
    hits: list[SearchHit] = field(default_factory=list)
    by_type: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "project_id": self.project_id,
            "total": len(self.hits),
            "by_type": self.by_type,
            "hits": [
                {"type": h.type, "id": h.id, "title": h.title, "snippet": h.snippet, "extra": h.extra}
                for h in self.hits
            ],
        }


async def unified_search(
    db: AsyncSession,
    project_id: str,
    query: str,
    *,
    types: Optional[list[str]] = None,
    limit_per_type: int = 10,
) -> SearchResult:
    """并行查询多个表,返回合并后的结果"""
    if not query or not query.strip():
        return SearchResult(query=query, project_id=project_id)

    selected = [t for t in (types or SUPPORTED_TYPES) if t in SUPPORTED_TYPES]
    if not selected:
        return SearchResult(query=query, project_id=project_id)

    pattern = f"%{query.strip()}%"

    coroutines = []
    for type_name in selected:
        coroutines.append(_query_type(db, type_name, project_id, pattern, limit_per_type))

    results = await asyncio.gather(*coroutines, return_exceptions=True)

    hits: list[SearchHit] = []
    by_type: dict[str, int] = {}
    for type_name, result in zip(selected, results):
        if isinstance(result, Exception):
            logger.warning(f"⚠️ 统一查询 [{type_name}] 失败: {result}")
            continue
        hits.extend(result)
        by_type[type_name] = len(result)

    return SearchResult(query=query, project_id=project_id, hits=hits, by_type=by_type)


async def _query_type(
    db: AsyncSession,
    type_name: str,
    project_id: str,
    pattern: str,
    limit: int,
) -> list[SearchHit]:
    """单类型查询调度"""
    if type_name == "character":
        return await _query_characters(db, project_id, pattern, limit)
    if type_name == "foreshadow":
        return await _query_foreshadows(db, project_id, pattern, limit)
    if type_name == "memory":
        return await _query_memories(db, project_id, pattern, limit)
    if type_name == "review":
        return await _query_reviews(db, project_id, pattern, limit)
    if type_name == "outline":
        return await _query_outlines(db, project_id, pattern, limit)
    if type_name == "chapter":
        return await _query_chapters(db, project_id, pattern, limit)
    if type_name == "commit":
        return await _query_commits(db, project_id, pattern, limit)
    return []


async def _query_characters(db, project_id, pattern, limit) -> list[SearchHit]:
    from app.models.character import Character
    result = await db.execute(
        select(Character)
        .where(Character.project_id == project_id)
        .where(or_(
            Character.name.ilike(pattern),
            Character.personality.ilike(pattern),
            Character.background.ilike(pattern),
        ))
        .limit(limit)
    )
    hits = []
    for c in result.scalars():
        snippet = (c.personality or c.background or "")[:80]
        hits.append(SearchHit(
            type="character",
            id=c.id,
            title=c.name,
            snippet=snippet,
            extra={"role_type": c.role_type},
        ))
    return hits


async def _query_foreshadows(db, project_id, pattern, limit) -> list[SearchHit]:
    from app.models.foreshadow import Foreshadow
    result = await db.execute(
        select(Foreshadow)
        .where(Foreshadow.project_id == project_id)
        .where(or_(
            Foreshadow.title.ilike(pattern),
            Foreshadow.content.ilike(pattern),
        ))
        .limit(limit)
    )
    return [
        SearchHit(
            type="foreshadow",
            id=f.id,
            title=f.title,
            snippet=(f.content or "")[:80],
            extra={
                "status": f.status,
                "plant_chapter": f.plant_chapter_number,
                "target_chapter": f.target_resolve_chapter_number,
            },
        )
        for f in result.scalars()
    ]


async def _query_memories(db, project_id, pattern, limit) -> list[SearchHit]:
    from app.models.memory import StoryMemory
    result = await db.execute(
        select(StoryMemory)
        .where(StoryMemory.project_id == project_id)
        .where(or_(
            StoryMemory.title.ilike(pattern),
            StoryMemory.content.ilike(pattern),
        ))
        .order_by(desc(StoryMemory.importance_score))
        .limit(limit)
    )
    return [
        SearchHit(
            type="memory",
            id=m.id,
            title=m.title or "(未命名记忆)",
            snippet=(m.content or "")[:80],
            extra={"memory_type": m.memory_type, "importance": m.importance_score},
        )
        for m in result.scalars()
    ]


async def _query_reviews(db, project_id, pattern, limit) -> list[SearchHit]:
    from app.models.chapter_review import ChapterReview
    result = await db.execute(
        select(ChapterReview)
        .where(ChapterReview.project_id == project_id)
        .where(or_(
            ChapterReview.title.ilike(pattern),
            ChapterReview.evidence.ilike(pattern),
            ChapterReview.fix_hint.ilike(pattern),
        ))
        .order_by(desc(ChapterReview.created_at))
        .limit(limit)
    )
    return [
        SearchHit(
            type="review",
            id=r.id,
            title=r.title,
            snippet=(r.fix_hint or r.evidence or "")[:80],
            extra={"dimension": r.dimension, "severity": r.severity, "chapter_id": r.chapter_id},
        )
        for r in result.scalars()
    ]


async def _query_outlines(db, project_id, pattern, limit) -> list[SearchHit]:
    from app.models.outline import Outline
    result = await db.execute(
        select(Outline)
        .where(Outline.project_id == project_id)
        .where(or_(
            Outline.title.ilike(pattern),
            Outline.content.ilike(pattern),
        ))
        .order_by(Outline.order_index)
        .limit(limit)
    )
    return [
        SearchHit(
            type="outline",
            id=o.id,
            title=o.title,
            snippet=(o.content or "")[:80],
            extra={"order_index": o.order_index},
        )
        for o in result.scalars()
    ]


async def _query_chapters(db, project_id, pattern, limit) -> list[SearchHit]:
    from app.models.chapter import Chapter
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .where(or_(
            Chapter.title.ilike(pattern),
            Chapter.summary.ilike(pattern),
            Chapter.content.ilike(pattern),
        ))
        .order_by(Chapter.chapter_number)
        .limit(limit)
    )
    return [
        SearchHit(
            type="chapter",
            id=c.id,
            title=f"第{c.chapter_number}章 {c.title}",
            snippet=(c.summary or (c.content or "")[:80])[:80],
            extra={"chapter_number": c.chapter_number, "word_count": c.word_count, "status": c.status},
        )
        for c in result.scalars()
    ]


async def _query_commits(db, project_id, pattern, limit) -> list[SearchHit]:
    from app.models.chapter_commit import ChapterCommit
    # commit 表只有 content_hash 可搜,搜索按章节号匹配查询关键字与 chapter_number 字符串
    # 实际意义不大,改为按 chapter_number 文本匹配
    if not pattern.strip("%").isdigit():
        return []
    try:
        num = int(pattern.strip("%"))
    except ValueError:
        return []
    result = await db.execute(
        select(ChapterCommit)
        .where(ChapterCommit.project_id == project_id)
        .where(ChapterCommit.chapter_number == num)
        .order_by(desc(ChapterCommit.created_at))
        .limit(limit)
    )
    return [
        SearchHit(
            type="commit",
            id=c.id,
            title=f"第{c.chapter_number}章快照",
            snippet=f"hash={c.content_hash[:8]} 字数={c.word_count}",
            extra={"chapter_id": c.chapter_id, "review_summary": c.review_summary or {}},
        )
        for c in result.scalars()
    ]
