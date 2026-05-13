"""提示词工坊 API（本地模式）"""
from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import INSTANCE_ID
from app.constants.prompt_categories import PROMPT_CATEGORIES
from app.database import get_db
from app.logger import get_logger
from app.models.prompt_workshop import PromptSubmission, PromptWorkshopItem, PromptWorkshopLike
from app.models.writing_style import WritingStyle
from app.schemas.prompt_workshop import (
    AdminItemCreate,
    AdminItemUpdate,
    ImportRequest,
    PromptSubmissionCreate,
    ReviewRequest,
)

router = APIRouter(prefix="/prompt-workshop", tags=["prompt-workshop"])
logger = get_logger(__name__)


# ==================== 依赖注入：身份与权限 ====================
# 通过 Depends 把"取登录用户/取管理员"这两个跨接口的横切关注点抽出来，
# 让 endpoint 签名直接表达自己的前置条件。

def current_user_id(request: Request) -> str:
    """要求已登录，返回本地 user_id"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    return user_id


def current_user_identifier(user_id: str = Depends(current_user_id)) -> str:
    """要求已登录，返回带 INSTANCE_ID 前缀的标识（兼容历史数据）"""
    return f"{INSTANCE_ID}:{user_id}"


def optional_user_identifier(request: Request) -> Optional[str]:
    """可选登录：未登录返回 None"""
    user_id = getattr(request.state, "user_id", None)
    return f"{INSTANCE_ID}:{user_id}" if user_id else None


def require_admin(request: Request):
    """要求当前用户为管理员"""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ==================== 内部辅助 ====================

async def _get_item_or_404(db: AsyncSession, item_id: str, only_active: bool = False) -> PromptWorkshopItem:
    query = select(PromptWorkshopItem).where(PromptWorkshopItem.id == item_id)
    if only_active:
        query = query.where(PromptWorkshopItem.status == "active")
    item = (await db.execute(query)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return item


async def _get_submission_or_404(
    db: AsyncSession,
    submission_id: str,
    submitter_id: Optional[str] = None,
) -> PromptSubmission:
    query = select(PromptSubmission).where(PromptSubmission.id == submission_id)
    if submitter_id is not None:
        query = query.where(PromptSubmission.submitter_id == submitter_id)
    submission = (await db.execute(query)).scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    return submission


def _item_to_dict(item: PromptWorkshopItem, is_liked: bool = False) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "prompt_content": item.prompt_content,
        "category": item.category,
        "tags": item.tags,
        "author_name": item.author_name,
        "is_official": item.is_official,
        "download_count": item.download_count,
        "like_count": item.like_count,
        "is_liked": is_liked,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _submission_to_dict(submission: PromptSubmission) -> dict:
    return {
        "id": submission.id,
        "name": submission.name,
        "description": submission.description,
        "prompt_content": submission.prompt_content,
        "category": submission.category,
        "tags": submission.tags,
        "author_display_name": submission.author_display_name,
        "is_anonymous": submission.is_anonymous,
        "status": submission.status,
        "review_note": submission.review_note,
        "reviewed_at": submission.reviewed_at.isoformat() if submission.reviewed_at else None,
        "created_at": submission.created_at.isoformat() if submission.created_at else None,
        "source_instance": submission.source_instance,
        "submitter_name": submission.submitter_name,
    }


# ==================== 公开 API ====================

@router.get("/status")
async def get_status():
    return {"mode": "local", "instance_id": INSTANCE_ID}


@router.get("/items")
async def get_items(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "newest",
    page: int = 1,
    limit: int = 20,
    user_identifier: Optional[str] = Depends(optional_user_identifier),
    db: AsyncSession = Depends(get_db),
):
    """获取提示词列表（公开接口，不需要登录）"""
    base_filters = [PromptWorkshopItem.status == "active"]
    if category:
        base_filters.append(PromptWorkshopItem.category == category)
    if search:
        base_filters.append(or_(
            PromptWorkshopItem.name.ilike(f"%{search}%"),
            PromptWorkshopItem.description.ilike(f"%{search}%"),
        ))

    query = select(PromptWorkshopItem).where(*base_filters)
    count_query = select(func.count(PromptWorkshopItem.id)).where(*base_filters)

    sort_column = {
        "popular": PromptWorkshopItem.like_count.desc(),
        "downloads": PromptWorkshopItem.download_count.desc(),
    }.get(sort, PromptWorkshopItem.created_at.desc())
    query = query.order_by(sort_column).offset((page - 1) * limit).limit(limit)

    total = (await db.execute(count_query)).scalar_one()
    items = (await db.execute(query)).scalars().all()

    liked_ids: set[str] = set()
    if user_identifier:
        like_rows = await db.execute(
            select(PromptWorkshopLike.workshop_item_id).where(
                PromptWorkshopLike.user_identifier == user_identifier
            )
        )
        liked_ids = {row[0] for row in like_rows.fetchall()}

    cat_rows = await db.execute(
        select(PromptWorkshopItem.category, func.count(PromptWorkshopItem.id))
        .where(PromptWorkshopItem.status == "active")
        .group_by(PromptWorkshopItem.category)
    )
    categories = [
        {"id": cat, "name": PROMPT_CATEGORIES.get(cat, cat), "count": count}
        for cat, count in cat_rows.fetchall()
    ]

    return {
        "success": True,
        "data": {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [_item_to_dict(item, is_liked=item.id in liked_ids) for item in items],
            "categories": categories,
        },
    }


@router.get("/items/{item_id}")
async def get_item(item_id: str, db: AsyncSession = Depends(get_db)):
    item = await _get_item_or_404(db, item_id, only_active=True)
    return {"success": True, "data": _item_to_dict(item)}


@router.post("/items/{item_id}/import")
async def import_item(
    item_id: str,
    data: ImportRequest,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """导入提示词到本地写作风格"""
    item = await _get_item_or_404(db, item_id)
    item.download_count += 1

    max_order = (await db.execute(
        select(func.count(WritingStyle.id)).where(WritingStyle.user_id == user_id)
    )).scalar_one()

    new_style = WritingStyle(
        user_id=user_id,
        name=data.custom_name or item.name,
        style_type="custom",
        description=f"从提示词工坊导入: {item.description or ''}",
        prompt_content=item.prompt_content,
        order_index=max_order + 1,
    )
    db.add(new_style)
    await db.commit()
    await db.refresh(new_style)

    return {
        "success": True,
        "message": "导入成功",
        "writing_style": {
            "id": new_style.id,
            "name": new_style.name,
            "style_type": new_style.style_type,
            "prompt_content": new_style.prompt_content,
        },
    }


@router.post("/items/{item_id}/like")
async def toggle_like(
    item_id: str,
    user_identifier: str = Depends(current_user_identifier),
    db: AsyncSession = Depends(get_db),
):
    """点赞/取消点赞"""
    item = await _get_item_or_404(db, item_id)

    existing = (await db.execute(
        select(PromptWorkshopLike).where(
            PromptWorkshopLike.user_identifier == user_identifier,
            PromptWorkshopLike.workshop_item_id == item_id,
        )
    )).scalar_one_or_none()

    if existing:
        await db.delete(existing)
        item.like_count = max(0, item.like_count - 1)
        liked = False
    else:
        db.add(PromptWorkshopLike(
            id=str(uuid.uuid4()),
            user_identifier=user_identifier,
            workshop_item_id=item_id,
        ))
        item.like_count += 1
        liked = True

    await db.commit()
    return {"success": True, "liked": liked, "like_count": item.like_count}


@router.post("/submit")
async def submit_prompt(
    data: PromptSubmissionCreate,
    request: Request,
    user_identifier: str = Depends(current_user_identifier),
    db: AsyncSession = Depends(get_db),
):
    """提交提示词等待管理员审核"""
    user = getattr(request.state, "user", None)
    submitter_name = (
        data.author_display_name
        or (user.display_name if user else None)
        or "未知用户"
    )

    submission = PromptSubmission(
        id=str(uuid.uuid4()),
        submitter_id=user_identifier,
        submitter_name=submitter_name,
        source_instance=INSTANCE_ID,
        name=data.name,
        description=data.description,
        prompt_content=data.prompt_content,
        category=data.category,
        tags=data.tags,
        author_display_name=data.author_display_name or submitter_name,
        is_anonymous=data.is_anonymous,
        status="pending",
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    return {
        "success": True,
        "message": "提交成功，等待管理员审核",
        "submission": {
            "id": submission.id,
            "status": submission.status,
            "created_at": submission.created_at.isoformat() if submission.created_at else None,
        },
    }


@router.get("/my-submissions")
async def get_my_submissions(
    status: Optional[str] = None,
    user_identifier: str = Depends(current_user_identifier),
    db: AsyncSession = Depends(get_db),
):
    """获取我的提交记录"""
    query = select(PromptSubmission).where(PromptSubmission.submitter_id == user_identifier)
    if status:
        query = query.where(PromptSubmission.status == status)
    query = query.order_by(PromptSubmission.created_at.desc())

    submissions = (await db.execute(query)).scalars().all()
    return {
        "success": True,
        "data": {
            "total": len(submissions),
            "items": [_submission_to_dict(s) for s in submissions],
        },
    }


@router.delete("/submissions/{submission_id}")
async def withdraw_submission(
    submission_id: str,
    force: bool = False,
    user_identifier: str = Depends(current_user_identifier),
    db: AsyncSession = Depends(get_db),
):
    """撤回（pending）或强制删除（已审核）自己的提交记录"""
    submission = await _get_submission_or_404(db, submission_id, submitter_id=user_identifier)

    if submission.status != "pending" and not force:
        raise HTTPException(status_code=400, detail="只能撤回待审核的提交，删除已审核记录请使用 force 参数")

    was_pending = submission.status == "pending"
    await db.delete(submission)
    await db.commit()

    return {"success": True, "message": "撤回成功" if was_pending else "删除成功"}


# ==================== 管理员 API ====================

@router.get("/admin/submissions")
async def admin_get_submissions(
    status: Optional[str] = None,
    source: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取审核列表（管理员）"""
    filters = []
    if status and status != "all":
        filters.append(PromptSubmission.status == status)
    if source:
        filters.append(PromptSubmission.source_instance == source)

    total = (await db.execute(
        select(func.count(PromptSubmission.id)).where(*filters)
    )).scalar_one()

    pending_count = (await db.execute(
        select(func.count(PromptSubmission.id)).where(PromptSubmission.status == "pending")
    )).scalar_one()

    submissions = (await db.execute(
        select(PromptSubmission)
        .where(*filters)
        .order_by(PromptSubmission.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).scalars().all()

    return {
        "success": True,
        "data": {
            "total": total,
            "pending_count": pending_count,
            "page": page,
            "limit": limit,
            "items": [_submission_to_dict(s) for s in submissions],
        },
    }


@router.post("/admin/submissions/{submission_id}/review")
async def admin_review_submission(
    submission_id: str,
    data: ReviewRequest,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """审核提交（通过/拒绝）"""
    submission = await _get_submission_or_404(db, submission_id)
    if submission.status != "pending":
        raise HTTPException(status_code=400, detail="该提交已被审核")

    admin_user_id = getattr(admin, "user_id", str(admin))
    submission.reviewer_id = admin_user_id
    submission.review_note = data.review_note
    submission.reviewed_at = datetime.utcnow()

    if data.action == "approve":
        new_item = PromptWorkshopItem(
            id=str(uuid.uuid4()),
            name=submission.name,
            description=submission.description,
            prompt_content=submission.prompt_content,
            category=data.category or submission.category,
            tags=data.tags or submission.tags,
            author_id=None if submission.is_anonymous else submission.submitter_id,
            author_name=submission.author_display_name if not submission.is_anonymous else None,
            source_instance=submission.source_instance,
            is_official=False,
            status="active",
        )
        db.add(new_item)
        submission.status = "approved"
        submission.workshop_item_id = new_item.id

        await db.commit()
        await db.refresh(new_item)
        return {"success": True, "message": "已通过审核并发布", "workshop_item": _item_to_dict(new_item)}

    submission.status = "rejected"
    await db.commit()
    await db.refresh(submission)
    return {"success": True, "message": "已拒绝", "submission": _submission_to_dict(submission)}


@router.post("/admin/items")
async def admin_create_item(
    data: AdminItemCreate,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """添加官方提示词"""
    new_item = PromptWorkshopItem(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        prompt_content=data.prompt_content,
        category=data.category,
        tags=data.tags,
        author_name="官方",
        is_official=True,
        status="active",
    )
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)
    return {"success": True, "item": _item_to_dict(new_item)}


@router.put("/admin/items/{item_id}")
async def admin_update_item(
    item_id: str,
    data: AdminItemUpdate,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """编辑提示词"""
    item = await _get_item_or_404(db, item_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return {"success": True, "item": _item_to_dict(item)}


@router.delete("/admin/items/{item_id}")
async def admin_delete_item(
    item_id: str,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除提示词"""
    item = await _get_item_or_404(db, item_id)
    await db.delete(item)
    await db.commit()
    return {"success": True, "message": "删除成功"}


@router.get("/admin/stats")
async def admin_get_stats(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取统计数据"""
    async def _scalar(stmt) -> int:
        return (await db.execute(stmt)).scalar_one() or 0

    total_items = await _scalar(
        select(func.count(PromptWorkshopItem.id)).where(PromptWorkshopItem.status == "active")
    )
    total_official = await _scalar(
        select(func.count(PromptWorkshopItem.id)).where(
            PromptWorkshopItem.status == "active",
            PromptWorkshopItem.is_official == True,  # noqa: E712
        )
    )
    total_pending = await _scalar(
        select(func.count(PromptSubmission.id)).where(PromptSubmission.status == "pending")
    )
    total_downloads = await _scalar(select(func.sum(PromptWorkshopItem.download_count)))
    total_likes = await _scalar(select(func.sum(PromptWorkshopItem.like_count)))

    return {
        "success": True,
        "data": {
            "total_items": total_items,
            "total_official": total_official,
            "total_pending": total_pending,
            "total_downloads": total_downloads,
            "total_likes": total_likes,
        },
    }
