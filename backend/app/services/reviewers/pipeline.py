"""审稿管线 - 并发执行多个 Reviewer 并聚合结果"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.logger import get_logger
from app.services.reviewers.base import BaseReviewer, ReviewContext, ReviewIssue

logger = get_logger(__name__)


class ReviewPipeline:
    """多维度审稿并行执行管线

    asyncio.gather 并行调度各 Reviewer,单维度失败不影响其他维度。
    """

    def __init__(self, reviewers: list[BaseReviewer]):
        if not reviewers:
            raise ValueError("ReviewPipeline 至少需要一个 Reviewer")
        self.reviewers = reviewers

    async def run(self, ctx: ReviewContext) -> list[ReviewIssue]:
        results = await asyncio.gather(
            *[r.review(ctx) for r in self.reviewers],
            return_exceptions=True,
        )
        all_issues: list[ReviewIssue] = []
        for reviewer, result in zip(self.reviewers, results):
            if isinstance(result, Exception):
                logger.warning(f"⚠️ Reviewer[{reviewer.dimension}] 抛出异常: {result}")
                continue
            all_issues.extend(result)
        logger.info(
            f"📝 审稿完成: 共 {len(all_issues)} 条问题 "
            f"(blocking={sum(1 for i in all_issues if i.severity == 'blocking')}, "
            f"warn={sum(1 for i in all_issues if i.severity == 'warn')}, "
            f"info={sum(1 for i in all_issues if i.severity == 'info')})"
        )
        return all_issues

    @classmethod
    def default(cls, ai_service) -> "ReviewPipeline":
        """注册全部 10 个标准审稿器"""
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

        return cls([
            ConsistencyReviewer(ai_service),
            TimelineReviewer(ai_service),
            OOCReviewer(ai_service),
            ContinuityReviewer(ai_service),
            LogicReviewer(ai_service),
            AIFlavorReviewer(ai_service),
            NarrativePromiseReviewer(ai_service),
            PacingReviewer(ai_service),
            HighPointReviewer(ai_service),
            ReaderPullReviewer(ai_service),
        ])
