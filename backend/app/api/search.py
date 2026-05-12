"""统一查询 API - /webnovel-query 等价端点"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.database import get_db
from app.logger import get_logger
from app.services.unified_search import SUPPORTED_TYPES, unified_search

router = APIRouter(prefix="/projects", tags=["统一查询"])
logger = get_logger(__name__)


@router.get("/{project_id}/search", summary="跨实体统一搜索")
async def project_search(
    project_id: str,
    request: Request,
    q: str = Query(..., min_length=1, description="搜索关键字"),
    types: Optional[str] = Query(
        None,
        description=f"逗号分隔的类型,留空查全部。支持:{','.join(SUPPORTED_TYPES)}",
    ),
    limit_per_type: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)

    type_list = None
    if types:
        type_list = [t.strip() for t in types.split(",") if t.strip()]
        unknown = [t for t in type_list if t not in SUPPORTED_TYPES]
        if unknown:
            raise HTTPException(status_code=400, detail=f"未知类型: {unknown}")

    result = await unified_search(
        db,
        project_id=project_id,
        query=q,
        types=type_list,
        limit_per_type=limit_per_type,
    )
    return result.to_dict()


@router.get("/_search/types", summary="列出支持的查询类型")
async def list_search_types():
    return {
        "types": list(SUPPORTED_TYPES),
        "descriptions": {
            "character": "角色(姓名/性格/背景)",
            "foreshadow": "伏笔(标题/内容)",
            "memory": "剧情记忆(标题/内容)",
            "review": "审稿意见(标题/原文/修改建议)",
            "outline": "大纲节点(标题/内容)",
            "chapter": "章节(标题/摘要/正文)",
            "commit": "章节快照(按章节号搜索)",
        },
    }
