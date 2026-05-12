"""章节多维度审稿器 - Chain of Responsibility 模式

每个 Reviewer 负责单一维度,通过 ReviewPipeline 并发执行后聚合 issues。
借鉴: webnovel-writer/agents/reviewer.md
"""
from app.services.reviewers.base import (
    BaseReviewer,
    ReviewContext,
    ReviewIssue,
    Severity,
)
from app.services.reviewers.consistency import ConsistencyReviewer
from app.services.reviewers.timeline import TimelineReviewer
from app.services.reviewers.ooc import OOCReviewer
from app.services.reviewers.continuity import ContinuityReviewer
from app.services.reviewers.logic import LogicReviewer
from app.services.reviewers.ai_flavor import AIFlavorReviewer
from app.services.reviewers.narrative_promise import NarrativePromiseReviewer
from app.services.reviewers.pacing import PacingReviewer
from app.services.reviewers.high_point import HighPointReviewer
from app.services.reviewers.reader_pull import ReaderPullReviewer
from app.services.reviewers.pipeline import ReviewPipeline

__all__ = [
    "BaseReviewer",
    "ReviewContext",
    "ReviewIssue",
    "Severity",
    "ConsistencyReviewer",
    "TimelineReviewer",
    "OOCReviewer",
    "ContinuityReviewer",
    "LogicReviewer",
    "AIFlavorReviewer",
    "NarrativePromiseReviewer",
    "PacingReviewer",
    "HighPointReviewer",
    "ReaderPullReviewer",
    "ReviewPipeline",
]
