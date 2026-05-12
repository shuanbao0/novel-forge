"""ChapterCommit Pydantic Schema"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChapterCommitResponse(BaseModel):
    id: str
    chapter_id: str
    project_id: str
    chapter_number: int
    word_count: int
    content_hash: str
    review_summary: dict = Field(default_factory=dict)
    fulfillment: dict = Field(default_factory=dict)
    extraction_meta: dict = Field(default_factory=dict)
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class ChapterCommitListResponse(BaseModel):
    items: List[ChapterCommitResponse]
    total: int
