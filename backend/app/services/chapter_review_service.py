"""章节审稿编排服务

职责:
- ReviewContextBuilder: 从 DB 装配审稿所需上下文
- run_chapter_review_background: 后台任务入口,被 PostGenPipeline 的 ChapterReviewHook 调度
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.services.reviewers import ReviewContext, ReviewPipeline

if TYPE_CHECKING:
    from app.models.chapter import Chapter
    from app.models.project import Project
    from app.services.ai_service import AIService

logger = get_logger(__name__)


class ReviewContextBuilder:
    """从 DB 拼装审稿上下文 - 与 ChapterContextBuilder 解耦,字段最小化"""

    async def build(self, db: AsyncSession, chapter: "Chapter") -> ReviewContext:
        from app.models.chapter import Chapter
        from app.models.project import Project

        project = await db.get(Project, chapter.project_id)

        previous_summary = ""
        if chapter.chapter_number > 1:
            prev_result = await db.execute(
                select(Chapter)
                .where(Chapter.project_id == chapter.project_id)
                .where(Chapter.chapter_number == chapter.chapter_number - 1)
            )
            prev_chapter = prev_result.scalar_one_or_none()
            if prev_chapter and prev_chapter.summary:
                previous_summary = prev_chapter.summary

        characters_info = await self._build_characters_brief(db, chapter.project_id)
        world_setting = self._build_world_setting(project)

        # 装载项目契约的承诺 + Genre Profile,供 reviewer 读取
        from app.services.creative_contract import CreativeContract
        from app.services.genre_profiles import get_profile, profile_to_prompt_block

        contract = CreativeContract.from_raw(project.creative_contract if project else None)
        metadata_extra: dict = {}
        if contract.narrative_promises:
            metadata_extra["narrative_promises"] = contract.narrative_promises

        genre_profile = get_profile(project.genre if project else "")
        if genre_profile:
            metadata_extra["genre_profile"] = profile_to_prompt_block(genre_profile)
            metadata_extra["genre_pacing"] = genre_profile.pacing_norm
            metadata_extra["genre_hook_density"] = genre_profile.hook_density_baseline
            metadata_extra["genre_reading_pull_floor"] = genre_profile.reading_pull_floor

        # 记忆便签 - 给所有 reviewer 看的剧情快照
        from app.services.memory_scratchpad import build_scratchpad

        try:
            pad = await build_scratchpad(db, chapter.project_id)
            scratchpad_text = pad.to_prompt_text()
            if scratchpad_text:
                metadata_extra["memory_scratchpad"] = scratchpad_text
        except Exception:
            pass

        return ReviewContext(
            chapter_id=chapter.id,
            chapter_number=chapter.chapter_number,
            chapter_title=chapter.title or "",
            chapter_content=chapter.content or "",
            project_title=project.title if project else "",
            project_genre=project.genre if project else "",
            project_theme=project.theme if project else "",
            narrative_perspective=(project.narrative_perspective if project else "") or "第三人称",
            previous_chapter_summary=previous_summary,
            characters_info=characters_info,
            world_setting=world_setting,
            metadata_extra=metadata_extra,
        )

    async def _build_characters_brief(self, db: AsyncSession, project_id: str, limit: int = 20) -> str:
        from app.models.character import Character

        result = await db.execute(
            select(Character)
            .where(Character.project_id == project_id)
            .limit(limit)
        )
        characters = result.scalars().all()
        if not characters:
            return ""
        lines = []
        for c in characters:
            personality = (c.personality or "")[:80]
            lines.append(
                f"- {c.name} [{c.role_type or '未指定'}]: {personality}"
            )
        return "\n".join(lines)

    def _build_world_setting(self, project: Optional["Project"]) -> str:
        if not project:
            return ""
        parts = []
        for label, value in [
            ("时代", project.world_time_period),
            ("地点", project.world_location),
            ("氛围", project.world_atmosphere),
            ("规则", project.world_rules),
        ]:
            if value:
                trimmed = value[:200]
                parts.append(f"{label}: {trimmed}")
        return "\n".join(parts)


async def _backfill_commit_review_summary(db, chapter_id: str, issues: list) -> None:
    """将审稿结果摘要 + 数据抽取事件回填到最近一次 ChapterCommit

    严格只 UPDATE 自己刚创建的快照,不破坏 append-only 语义。
    """
    from sqlalchemy import desc, select
    from app.models.chapter import Chapter
    from app.models.chapter_commit import ChapterCommit
    from app.services.data_extractor import extract_events_from_text

    try:
        result = await db.execute(
            select(ChapterCommit)
            .where(ChapterCommit.chapter_id == chapter_id)
            .order_by(desc(ChapterCommit.created_at))
            .limit(1)
        )
        commit = result.scalar_one_or_none()
        if not commit:
            return
        by_sev: dict = {}
        by_dim: dict = {}
        for i in issues:
            by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
            by_dim[i.dimension] = by_dim.get(i.dimension, 0) + 1
        commit.review_summary = {
            "total": len(issues),
            "by_severity": by_sev,
            "by_dimension": by_dim,
        }

        # 填充事件抽取 + 实体消歧(关键词 + 字符串匹配,零 LLM 成本)
        chapter = await db.get(Chapter, chapter_id)
        if chapter and chapter.content:
            from app.models.character import Character
            from sqlalchemy import select as _select
            from app.services.entity_disambiguator import disambiguate

            events = extract_events_from_text(chapter.content, max_events=12)

            chars_result = await db.execute(
                _select(Character.name).where(Character.project_id == chapter.project_id)
            )
            known_names = [n for n in chars_result.scalars().all() if n]
            candidates = disambiguate(chapter.content, known_names)

            # 读者抓力评分
            from app.services.reading_pull import compute as compute_reading_pull
            from app.services.genre_profiles import get_profile

            project_for_genre = await db.get(__import__('app.models.project', fromlist=['Project']).Project, chapter.project_id)
            profile = get_profile(project_for_genre.genre if project_for_genre else "")
            pull_score = compute_reading_pull(
                content=chapter.content,
                review_issues=[
                    {"severity": i.severity, "dimension": i.dimension}
                    for i in issues
                ],
                events=[e.to_dict() for e in events],
                hook_density_baseline=profile.hook_density_baseline if profile else 2,
                reading_pull_floor=profile.reading_pull_floor if profile else 60,
            )

            commit.extraction_meta = {
                **(commit.extraction_meta or {}),
                "events": [e.to_dict() for e in events],
                "events_count": len(events),
                "disambiguation": [
                    {
                        "surface": c.surface,
                        "confidence": c.confidence,
                        "suggestion": c.suggestion,
                        "occurrences": c.occurrences,
                        "similar_to": c.similar_to or None,
                    }
                    for c in candidates[:15]
                ],
                "reading_pull": pull_score.to_dict(),
            }
        await db.commit()
    except Exception as exc:
        logger.warning(f"⚠️ 回填 ChapterCommit 摘要 + 事件失败: {exc}")


async def run_chapter_review_background(
    chapter_id: str,
    project_id: str,
    user_id: str,
    ai_service: "AIService",
) -> bool:
    """章节审稿后台入口

    创建独立 DB 会话,装配 ReviewContext,运行 ReviewPipeline,持久化 issues。
    """
    from app.database import get_engine
    from app.models.chapter import Chapter
    from app.models.chapter_review import ChapterReview
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as BgAsyncSession

    engine = await get_engine(user_id)
    session_maker = async_sessionmaker(engine, class_=BgAsyncSession, expire_on_commit=False)
    run_id = str(uuid.uuid4())

    async with session_maker() as db:
        try:
            chapter = await db.get(Chapter, chapter_id)
            if not chapter or not chapter.content:
                logger.warning(f"⚠️ 审稿跳过 - 章节不存在或为空: {chapter_id}")
                return False

            logger.info(f"🔍 开始审稿章节 {chapter_id} (run_id={run_id})")
            ctx = await ReviewContextBuilder().build(db, chapter)

            pipeline = ReviewPipeline.default(ai_service)
            issues = await pipeline.run(ctx)

            if issues:
                rows = [
                    ChapterReview(
                        chapter_id=chapter_id,
                        project_id=project_id,
                        user_id=user_id,
                        review_run_id=run_id,
                        dimension=issue.dimension,
                        severity=issue.severity,
                        category=issue.category or None,
                        title=issue.title,
                        evidence=issue.evidence or None,
                        fix_hint=issue.fix_hint or None,
                    )
                    for issue in issues
                ]
                db.add_all(rows)
                await db.commit()
                logger.info(f"✅ 已写入 {len(rows)} 条审稿意见 (chapter={chapter_id}, run={run_id})")
            else:
                logger.info(f"✅ 章节审稿无问题 (chapter={chapter_id})")

            # 把审稿摘要回填到最近一次 ChapterCommit(append-only,只更新自己创建的快照)
            await _backfill_commit_review_summary(db, chapter_id, issues)
            return True
        except Exception as exc:
            logger.error(f"❌ 章节审稿失败 {chapter_id}: {exc}", exc_info=True)
            try:
                await db.rollback()
            except Exception:
                pass
            return False
