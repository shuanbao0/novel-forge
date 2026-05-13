"""章节生成 Prompt 装配 - 统一三条生成路径（SSE 流式 / 后台 / 批量）的拼装逻辑

设计目标：
- 把"按大纲模式 × 是否首章 选模板 → 用 chapter_context 字段填充 → 装饰器管线包装"
  这一整套准备动作，从 api/chapters.py 三处重复实现中抽出
- 模板分支用 dispatch dict 派发（Strategy / Table-driven），避免 4 段相似 if/else
- 装饰器装配通过 PromptPipeline.for_chapter_generation 工厂复用
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.services.creative_contract import (
    ChapterBrief,
    CreativeContract,
    VolumeBrief,
)
from app.services.prompt_decorators import PromptContext, PromptPipeline
from app.services.prompt_service import PromptService

if TYPE_CHECKING:
    from app.models.chapter import Chapter
    from app.models.outline import Outline
    from app.models.project import Project

logger = get_logger(__name__)

# (outline_mode, has_continuation) -> 模板键
_TEMPLATE_KEY = {
    ("one-to-one", True): "CHAPTER_GENERATION_ONE_TO_ONE_NEXT",
    ("one-to-one", False): "CHAPTER_GENERATION_ONE_TO_ONE",
    ("one-to-many", True): "CHAPTER_GENERATION_ONE_TO_MANY_NEXT",
    ("one-to-many", False): "CHAPTER_GENERATION_ONE_TO_MANY",
}


def _normalize_mode(outline_mode: Optional[str]) -> str:
    return "one-to-one" if outline_mode == "one-to-one" else "one-to-many"


async def build_base_chapter_prompt(
    *,
    db: AsyncSession,
    user_id: str,
    project: "Project",
    outline_mode: Optional[str],
    chapter: "Chapter",
    chapter_context,
    target_word_count: int,
    narrative_perspective: str,
    fallback_previous_summary: Optional[str] = None,
) -> str:
    """根据大纲模式与上下文，从模板生成基础 prompt。

    覆盖四种分支：(1-1, 续写)/(1-1, 首章)/(1-N, 续写)/(1-N, 首章)。
    fallback_previous_summary 仅在 1-N 续写场景下作为最后兜底。
    """
    mode = _normalize_mode(outline_mode)
    has_continuation = bool(chapter_context.continuation_point)
    template_name = _TEMPLATE_KEY[(mode, has_continuation)]
    template = await PromptService.get_template(template_name, user_id, db)

    fmt_kwargs = dict(
        project_title=project.title,
        chapter_number=chapter.chapter_number,
        chapter_title=chapter.title,
        chapter_outline=chapter_context.chapter_outline,
        target_word_count=target_word_count,
        genre=project.genre or "未设定",
        narrative_perspective=narrative_perspective,
        characters_info=chapter_context.chapter_characters or "暂无角色信息",
        chapter_careers=chapter_context.chapter_careers or "暂无职业信息",
        foreshadow_reminders=chapter_context.foreshadow_reminders or "暂无需要关注的伏笔",
        relevant_memories=chapter_context.relevant_memories or "暂无相关记忆",
    )

    if has_continuation:
        if mode == "one-to-one":
            fmt_kwargs["previous_chapter_content"] = chapter_context.continuation_point
            fmt_kwargs["previous_chapter_summary"] = (
                chapter_context.previous_chapter_summary or "（无上一章摘要）"
            )
        else:  # one-to-many
            fmt_kwargs["continuation_point"] = chapter_context.continuation_point
            fmt_kwargs["previous_chapter_summary"] = (
                chapter_context.previous_chapter_summary
                or fallback_previous_summary
                or "（无上一章摘要，请根据锚点续写）"
            )
            fmt_kwargs["recent_chapters_context"] = (
                chapter_context.recent_chapters_context or ""
            )
            # 1-N 续写历史上对相关记忆使用空串 fallback，与原行为一致
            fmt_kwargs["relevant_memories"] = chapter_context.relevant_memories or ""

    return PromptService.format_prompt(template, **fmt_kwargs)


async def build_decorated_chapter_pipeline(
    *,
    db: AsyncSession,
    project: "Project",
    outline: Optional["Outline"],
    chapter: "Chapter",
    style_content: Optional[str],
    anti_ai_enabled: bool = True,
) -> PromptPipeline:
    """装配章节生成的 PromptPipeline（含契约 / 便签 / 风格模式 / 反 AI / 输出格式）。

    所有上下文准备（contract / volume_brief / chapter_brief / scratchpad / pattern）
    均在此完成，调用方只需提交 base_prompt 即可。
    """
    project_contract = CreativeContract.from_raw(
        getattr(project, "creative_contract", None)
    )
    volume_brief = (
        VolumeBrief.from_raw(getattr(outline, "creative_brief", None))
        if outline
        else VolumeBrief()
    )
    chapter_brief = ChapterBrief.from_raw(getattr(chapter, "creative_brief", None))

    try:
        from app.services.memory_scratchpad import build_scratchpad
        pad = await build_scratchpad(db, project.id)
        scratchpad_text = pad.to_prompt_text()
    except Exception as exc:
        logger.warning(f"⚠️ 记忆便签构建失败（跳过）: {exc}")
        scratchpad_text = ""

    from app.services.style_pattern_extractor import style_pattern_from_raw
    style_pattern_text = style_pattern_from_raw(
        getattr(project, "style_patterns", None)
    ).to_prompt_block()

    return PromptPipeline.for_chapter_generation(
        style_content=style_content,
        anti_ai_enabled=anti_ai_enabled,
        contract=project_contract,
        volume_brief=volume_brief,
        chapter_brief=chapter_brief,
        scratchpad_text=scratchpad_text,
        style_pattern_text=style_pattern_text,
    )


async def assemble_chapter_prompt(
    *,
    db: AsyncSession,
    user_id: str,
    project: "Project",
    outline: Optional["Outline"],
    outline_mode: Optional[str],
    chapter: "Chapter",
    chapter_context,
    target_word_count: int,
    narrative_perspective: str,
    style_content: Optional[str],
    fallback_previous_summary: Optional[str] = None,
    anti_ai_enabled: bool = True,
) -> tuple[str, Optional[str], dict]:
    """便利入口：一次完成 base_prompt 生成 + 装饰器管线运行。

    返回 (user_prompt, system_prompt, metadata)，metadata 暴露各装饰器的应用情况
    供调用方按需 log。
    """
    base_prompt = await build_base_chapter_prompt(
        db=db,
        user_id=user_id,
        project=project,
        outline_mode=outline_mode,
        chapter=chapter,
        chapter_context=chapter_context,
        target_word_count=target_word_count,
        narrative_perspective=narrative_perspective,
        fallback_previous_summary=fallback_previous_summary,
    )
    pipeline = await build_decorated_chapter_pipeline(
        db=db,
        project=project,
        outline=outline,
        chapter=chapter,
        style_content=style_content,
        anti_ai_enabled=anti_ai_enabled,
    )
    ctx = pipeline.run(PromptContext(user_prompt=base_prompt))
    return ctx.user_prompt, ctx.system_prompt, ctx.metadata
