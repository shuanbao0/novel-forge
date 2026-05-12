"""写作模式抽取 API - /webnovel-learn 等价端点"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.database import get_db
from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.project import Project
from app.services.style_pattern_extractor import (
    extract_from_chapters,
    style_pattern_from_raw,
)

router = APIRouter(prefix="/projects", tags=["写作模式"])
logger = get_logger(__name__)


@router.get("/{project_id}/style-patterns", summary="读取已抽取的写作模式")
async def get_style_patterns(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    pattern = style_pattern_from_raw(project.style_patterns)
    return {
        "project_id": project_id,
        "has_data": not pattern.is_empty(),
        "pattern": pattern.to_dict(),
        "prompt_block": pattern.to_prompt_block(),
    }


@router.post("/{project_id}/learn-style", summary="从已写章节抽取写作模式并落库")
async def learn_style(
    project_id: str,
    request: Request,
    sample_limit: int = Query(20, ge=1, le=100, description="最多分析多少章"),
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    chapters_result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .where(Chapter.status == "completed")
        .order_by(asc(Chapter.chapter_number))
    )
    chapters = list(chapters_result.scalars().all())
    if not chapters:
        raise HTTPException(status_code=400, detail="项目尚无已完成章节,无法抽取风格")

    pattern = extract_from_chapters(
        [c.content for c in chapters if c.content],
        sample_limit=sample_limit,
    )
    project.style_patterns = pattern.to_dict()
    await db.commit()
    logger.info(f"🪞 项目 {project_id} 抽取写作模式: {pattern.sample_chapter_count} 章 {pattern.sample_word_count} 字")
    return {
        "project_id": project_id,
        "pattern": pattern.to_dict(),
        "prompt_block": pattern.to_prompt_block(),
    }


@router.delete("/{project_id}/style-patterns", summary="清空写作模式快照")
async def clear_style_patterns(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.style_patterns = None
    await db.commit()
    return {"success": True}
