"""章节审稿 API - 拉取问题列表 / 修改状态 / 重跑审稿"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_review import ChapterReview
from app.schemas.chapter_review import (
    ChapterReviewListResponse,
    ChapterReviewResponse,
    ChapterReviewSummary,
    RerunReviewResponse,
    ReviewActionResponse,
)
from app.services.ai_service import AIService
from app.services.chapter_review_service import run_chapter_review_background

router = APIRouter(prefix="/chapters", tags=["章节审稿"])
logger = get_logger(__name__)


async def _load_chapter(db: AsyncSession, chapter_id: str, user_id: str) -> Chapter:
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, user_id, db)
    return chapter


@router.get(
    "/{chapter_id}/reviews",
    response_model=ChapterReviewListResponse,
    summary="获取章节审稿意见列表",
)
async def list_chapter_reviews(
    chapter_id: str,
    request: Request,
    status_filter: str = Query(None, alias="status", description="状态: open/ignored/fixed"),
    run_id: str = Query(None, description="按审稿批次过滤;不填则取最近一次"),
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await _load_chapter(db, chapter_id, user_id)

    # 找到目标 run_id
    target_run_id = run_id
    if not target_run_id:
        latest = await db.execute(
            select(ChapterReview.review_run_id, func.max(ChapterReview.created_at).label("at"))
            .where(ChapterReview.chapter_id == chapter_id)
            .group_by(ChapterReview.review_run_id)
            .order_by(desc("at"))
            .limit(1)
        )
        row = latest.first()
        target_run_id = row[0] if row else None

    items: list[ChapterReview] = []
    summary = ChapterReviewSummary()

    if target_run_id:
        query = select(ChapterReview).where(
            ChapterReview.chapter_id == chapter_id,
            ChapterReview.review_run_id == target_run_id,
        )
        if status_filter:
            query = query.where(ChapterReview.status == status_filter)
        result = await db.execute(query.order_by(ChapterReview.severity, ChapterReview.created_at))
        items = list(result.scalars().all())

        summary.latest_run_id = target_run_id
        if items:
            summary.latest_run_at = max(i.created_at for i in items if i.created_at)
        summary.total = len(items)
        for issue in items:
            summary.by_severity[issue.severity] = summary.by_severity.get(issue.severity, 0) + 1
            summary.by_dimension[issue.dimension] = summary.by_dimension.get(issue.dimension, 0) + 1

    return ChapterReviewListResponse(
        items=[ChapterReviewResponse.model_validate(i) for i in items],
        summary=summary,
    )


@router.post(
    "/{chapter_id}/reviews/{review_id}/ignore",
    response_model=ReviewActionResponse,
    summary="忽略某条审稿意见",
)
async def ignore_review(
    chapter_id: str,
    review_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await _load_chapter(db, chapter_id, user_id)
    review = await db.get(ChapterReview, review_id)
    if not review or review.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="审稿意见不存在")
    review.status = "ignored"
    await db.commit()
    return ReviewActionResponse(success=True, message="已忽略")


@router.post(
    "/{chapter_id}/reviews/{review_id}/resolve",
    response_model=ReviewActionResponse,
    summary="标记某条审稿意见为已修复",
)
async def resolve_review(
    chapter_id: str,
    review_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await _load_chapter(db, chapter_id, user_id)
    review = await db.get(ChapterReview, review_id)
    if not review or review.chapter_id != chapter_id:
        raise HTTPException(status_code=404, detail="审稿意见不存在")
    review.status = "fixed"
    await db.commit()
    return ReviewActionResponse(success=True, message="已标记为已修复")


@router.post(
    "/{chapter_id}/reviews/rerun",
    response_model=RerunReviewResponse,
    summary="重跑章节审稿(新建一批审稿意见)",
)
async def rerun_review(
    chapter_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ai_service: AIService = Depends(get_user_ai_service),
):
    user_id = getattr(request.state, "user_id", None)
    chapter = await _load_chapter(db, chapter_id, user_id)
    if not chapter.content:
        raise HTTPException(status_code=400, detail="章节尚无正文,无法审稿")

    background_tasks.add_task(
        run_chapter_review_background,
        chapter_id=chapter_id,
        project_id=chapter.project_id,
        user_id=user_id,
        ai_service=ai_service,
    )
    return RerunReviewResponse(success=True, scheduled=True, message="审稿任务已排队")
