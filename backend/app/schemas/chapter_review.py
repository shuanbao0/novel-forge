"""章节审稿 Pydantic Schema"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChapterReviewResponse(BaseModel):
    id: str
    chapter_id: str
    project_id: str
    review_run_id: str
    dimension: str
    severity: str
    category: Optional[str] = None
    title: str
    evidence: Optional[str] = None
    fix_hint: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChapterReviewSummary(BaseModel):
    """按维度/严重级聚合的统计"""
    total: int = 0
    by_severity: dict = Field(default_factory=dict)
    by_dimension: dict = Field(default_factory=dict)
    latest_run_id: Optional[str] = None
    latest_run_at: Optional[datetime] = None


class ChapterReviewListResponse(BaseModel):
    items: List[ChapterReviewResponse]
    summary: ChapterReviewSummary


class ReviewActionResponse(BaseModel):
    success: bool
    message: str = ""


class RerunReviewResponse(BaseModel):
    success: bool
    message: str = ""
    scheduled: bool = False
