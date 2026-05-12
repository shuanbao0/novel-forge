"""章节 Commit API - 只读快照历史"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.database import get_db
from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_commit import ChapterCommit
from app.schemas.chapter_commit import (
    ChapterCommitListResponse,
    ChapterCommitResponse,
)

router = APIRouter(prefix="/chapters", tags=["章节快照"])
logger = get_logger(__name__)


@router.get(
    "/{chapter_id}/commits",
    response_model=ChapterCommitListResponse,
    summary="列出章节的所有快照",
)
async def list_chapter_commits(
    chapter_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, user_id, db)

    total_q = await db.execute(
        select(func.count(ChapterCommit.id)).where(ChapterCommit.chapter_id == chapter_id)
    )
    total = total_q.scalar_one() or 0

    result = await db.execute(
        select(ChapterCommit)
        .where(ChapterCommit.chapter_id == chapter_id)
        .order_by(desc(ChapterCommit.created_at))
        .limit(limit)
    )
    commits = list(result.scalars().all())
    return ChapterCommitListResponse(
        items=[ChapterCommitResponse.model_validate(c.to_dict()) for c in commits],
        total=total,
    )


@router.get(
    "/{chapter_id}/commits/latest",
    response_model=ChapterCommitResponse,
    summary="获取章节最新快照",
)
async def get_latest_commit(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, user_id, db)

    result = await db.execute(
        select(ChapterCommit)
        .where(ChapterCommit.chapter_id == chapter_id)
        .order_by(desc(ChapterCommit.created_at))
        .limit(1)
    )
    commit = result.scalar_one_or_none()
    if not commit:
        raise HTTPException(status_code=404, detail="尚无快照")
    return ChapterCommitResponse.model_validate(commit.to_dict())
