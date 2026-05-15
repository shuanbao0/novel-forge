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
from app.services.prompt_decorators import (
    CharacterArcDecorator,
    FactConsistencyDecorator,
    LocationVarietyDecorator,
    MotifCoolingDecorator,
    NarratorVoiceDecorator,
    PacingMilestoneDecorator,
    PlotBeatCoolingDecorator,
    PromptContext,
    PromptPipeline,
    StoryTimelineDecorator,
)
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

    # 硬上限在 Python 侧算好,避免 prompt 里出现 "4000*1.2" 这种需要 LLM 心算的写法。
    # 与生成端 hard_cap=target*1.3 + max_tokens=target*1.0 形成三层防线,
    # 这里 1.2 是给 AI 的"明面承诺",留 0.1 的余量缓冲断流。
    hard_ceiling = int(target_word_count * 1.2)

    fmt_kwargs = dict(
        project_title=project.title,
        chapter_number=chapter.chapter_number,
        chapter_title=chapter.title,
        chapter_outline=chapter_context.chapter_outline,
        target_word_count=target_word_count,
        hard_ceiling=hard_ceiling,
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


def _build_narrator_voice_decorator(project: "Project") -> Optional[NarratorVoiceDecorator]:
    """从 project.generation_settings.protagonist_voice 构造装饰器。

    配置缺失时返回 None,装饰器工厂会自动跳过它。
    """
    settings = getattr(project, "generation_settings", None) or {}
    if not isinstance(settings, dict):
        return None
    voice = settings.get("protagonist_voice")
    if not isinstance(voice, dict):
        return None
    age = voice.get("age")
    era = voice.get("era")
    forbidden = voice.get("forbidden_vocab") or []
    if not isinstance(forbidden, list):
        forbidden = []
    if not (age or era or forbidden):
        return None
    return NarratorVoiceDecorator(age=age, era=era, forbidden_vocab=forbidden)


async def _fetch_recent_plot_analyses(
    db: AsyncSession,
    project_id: str,
    current_chapter: int,
    lookback: int,
):
    """加载最近 N 章已完成的 PlotAnalysis 记录(按 chapter_number 升序)。

    PlotAnalysis 没有 chapter_number 列,需要 JOIN Chapter 表。
    第 1 章或仓库无数据时返回空列表。
    """
    if current_chapter <= 1 or lookback <= 0:
        return []
    from sqlalchemy import select
    from app.models.chapter import Chapter
    from app.models.memory import PlotAnalysis

    lower = max(1, current_chapter - lookback)
    q = await db.execute(
        select(PlotAnalysis, Chapter.chapter_number)
        .join(Chapter, Chapter.id == PlotAnalysis.chapter_id)
        .where(Chapter.project_id == project_id)
        .where(Chapter.chapter_number >= lower)
        .where(Chapter.chapter_number < current_chapter)
        .order_by(Chapter.chapter_number.asc())
    )
    return [pa for (pa, _) in q.all()]


async def _build_character_arc_decorator(
    db: AsyncSession,
    project_id: str,
    chapter_number: int,
) -> Optional[CharacterArcDecorator]:
    """聚合最近 5 章每个角色的最新状态 + 关系变化,构造装饰器。

    多章中同一角色多次出现时,后出现的覆盖前面(取最新)。
    无数据时返回 None,管线无感跳过。
    """
    try:
        analyses = await _fetch_recent_plot_analyses(db, project_id, chapter_number, lookback=5)
    except Exception as exc:
        logger.warning(f"⚠️ 角色弧线读取失败(跳过): {exc}")
        return None
    if not analyses:
        return None
    # name -> 最新状态字典
    latest: dict[str, dict] = {}
    for pa in analyses:
        states = pa.character_states or []
        if not isinstance(states, list):
            continue
        for s in states:
            if not isinstance(s, dict):
                continue
            name = (s.get("character_name") or "").strip()
            if not name:
                continue
            state_after = (s.get("state_after") or "").strip()
            psych = (s.get("psychological_change") or "").strip()
            rel_changes = s.get("relationship_changes") or {}
            rel_text = ""
            if isinstance(rel_changes, dict) and rel_changes:
                pairs = [f"与{k}: {v}" for k, v in list(rel_changes.items())[:3] if v]
                rel_text = "; ".join(pairs)
            combined_state = state_after or psych
            if not combined_state and not rel_text:
                continue
            latest[name] = {
                "name": name,
                "state": combined_state,
                "relationships": rel_text,
            }
    if not latest:
        return None
    return CharacterArcDecorator(arcs=list(latest.values()))


async def _build_location_variety_decorator(
    db: AsyncSession,
    project_id: str,
    chapter_number: int,
) -> Optional[LocationVarietyDecorator]:
    """从最近 3 章 PlotAnalysis.scenes 取地点,构造装饰器。

    取近期 3 章已经发生的场景, 用作"避免再次出现"的提示。
    无数据时返回 None。
    """
    try:
        analyses = await _fetch_recent_plot_analyses(db, project_id, chapter_number, lookback=3)
    except Exception as exc:
        logger.warning(f"⚠️ 场景列表读取失败(跳过): {exc}")
        return None
    if not analyses:
        return None
    locations: list[str] = []
    for pa in analyses:
        scenes = pa.scenes or []
        if not isinstance(scenes, list):
            continue
        for scene in scenes:
            if isinstance(scene, dict):
                loc = scene.get("location")
                if isinstance(loc, str) and loc.strip():
                    locations.append(loc.strip())
    if not locations:
        return None
    return LocationVarietyDecorator(recent_locations=locations)


async def _build_fact_consistency_decorator(
    db: AsyncSession,
    project_id: str,
) -> Optional[FactConsistencyDecorator]:
    """从 FactLedgerRepository 加载项目级事实台账, 构造装饰器.

    空台账 / 第 1 章前 / 仓储异常 → 返回 None, 装饰器管线无感跳过.
    """
    try:
        from app.repositories.fact_ledger_repo import FactLedgerRepository
        ledger = await FactLedgerRepository(db).get(project_id)
    except Exception as exc:
        logger.warning(f"⚠️ 事实台账读取失败(跳过): {exc}")
        return None
    block = ledger.to_prompt_block()
    if not block:
        return None
    return FactConsistencyDecorator(ledger_block=block)


async def _build_plot_beat_cooling_decorator(
    db: AsyncSession,
    project_id: str,
    chapter_number: int,
) -> Optional[PlotBeatCoolingDecorator]:
    """从最近 5 章 PlotAnalysis.plot_points[i].scene_skeleton 构造装饰器。

    数据契约: PLOT_ANALYSIS 模板要求 LLM 在每个 plot_point 内嵌 scene_skeleton:
        {"location": "...", "action_kind": "训话|对峙|...",
         "role_pair_key": "a↔b", "emotion_beat": "压制|和解|..."}
    importance < 0.6 的 plot_point 也保留(低强度场景同样会被复读),
    PER_CHAPTER_CAP 限制每章最多 3 条骨架以控制 prompt 长度.

    枚举归一化: LLM 不会严格遵守 7/6 个枚举值, 经常输出"训诫/质问"等近义词,
    通过 scene_skeleton_normalize 模块映射回规范值, 让"训诫"和"训话"被
    PlotBeatCoolingDecorator._compute_hot() 当作同一维度累计计数.
    role_pair_key 也做字典序归一化, 防止"a↔b"与"b↔a"被当成两对.

    向后兼容: 旧 plot_points 缺 scene_skeleton 时整条跳过, 全部跳过则返回 None,
    管线无感关闭, 不会回退到旧的"文本去重"误判模式.
    """
    if chapter_number <= 1:
        return None
    try:
        analyses = await _fetch_recent_plot_analyses(db, project_id, chapter_number, lookback=5)
    except Exception as exc:
        logger.warning(f"⚠️ 场景骨架读取失败(跳过): {exc}")
        return None
    if not analyses:
        return None

    pa_to_chapter: dict[str, int] = {}
    from sqlalchemy import select
    from app.models.chapter import Chapter
    from app.models.memory import PlotAnalysis
    from app.services.scene_skeleton_normalize import (
        normalize_action_kind, normalize_emotion_beat, normalize_role_pair_key,
    )

    lower = max(1, chapter_number - 5)
    q = await db.execute(
        select(PlotAnalysis.id, Chapter.chapter_number)
        .join(Chapter, Chapter.id == PlotAnalysis.chapter_id)
        .where(Chapter.project_id == project_id)
        .where(Chapter.chapter_number >= lower)
        .where(Chapter.chapter_number < chapter_number)
    )
    for pid, ch_num in q.all():
        pa_to_chapter[pid] = ch_num

    skeletons: list[dict] = []
    PER_CHAPTER_CAP = 3
    for pa in analyses:
        ch_num = pa_to_chapter.get(pa.id)
        points = pa.plot_points or []
        if not isinstance(points, list):
            continue
        kept = 0
        for p in points:
            if not isinstance(p, dict):
                continue
            skel = p.get("scene_skeleton")
            if not isinstance(skel, dict):
                continue
            location = (skel.get("location") or "").strip()
            action = normalize_action_kind(skel.get("action_kind"))
            pair = normalize_role_pair_key(skel.get("role_pair_key"))
            emotion = normalize_emotion_beat(skel.get("emotion_beat"))
            if not (location and action and pair and emotion):
                continue
            skeletons.append({
                "chapter_number": ch_num,
                "location": location,
                "action_kind": action,
                "role_pair_key": pair,
                "emotion_beat": emotion,
            })
            kept += 1
            if kept >= PER_CHAPTER_CAP:
                break
    if not skeletons:
        return None
    return PlotBeatCoolingDecorator(recent_skeletons=skeletons)


async def _build_motif_cooling_decorator(
    db: AsyncSession,
    project_id: str,
    chapter_number: int,
) -> Optional[MotifCoolingDecorator]:
    """从 MotifRepository 读取近期已用意象,构造冷却装饰器。

    第一章 / 仓库为空 / 查询失败 时返回 None,管线无感跳过。
    """
    if chapter_number <= 1:
        return None
    try:
        from app.repositories.motif_repo import MotifRepository
    except ImportError:
        # 在 Phase 3 落地前先不强求依赖存在
        return None
    try:
        repo = MotifRepository(db)
        cooling = await repo.get_cooling(project_id, chapter_number, lookback=3)
        banned = await repo.get_overused(project_id, threshold=5)
    except Exception as exc:
        logger.warning(f"⚠️ 意象去重数据读取失败（跳过）: {exc}")
        return None
    if not cooling and not banned:
        return None
    return MotifCoolingDecorator(cooling=cooling, banned=banned)


def _extract_time_fields(raw_plan) -> tuple[str, str]:
    """从一个 expansion_plan(JSON 串或 dict)取出 (anchor, advance) 文本。

    任意失败/缺失都返回 ("", ""),由装饰器层做"两端皆空就跳过"的判断。
    """
    if not raw_plan:
        return "", ""
    try:
        import json as _json
        plan = _json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
    except (TypeError, ValueError):
        return "", ""
    if not isinstance(plan, dict):
        return "", ""
    return (
        (plan.get("story_time_anchor") or "").strip(),
        (plan.get("story_time_advance") or "").strip(),
    )


def _build_pacing_milestone_decorator(
    volume_brief: VolumeBrief,
    chapter_number: int,
) -> Optional[PacingMilestoneDecorator]:
    """从 VolumeBrief.pacing_milestones 构造装饰器.

    无配置或装饰器分类后两组都为空时返回 None,工厂自动跳过。
    """
    milestones = volume_brief.pacing_milestones if volume_brief else []
    if not milestones:
        return None
    deco = PacingMilestoneDecorator(
        milestones=milestones,
        current_chapter=chapter_number,
    )
    return deco if deco._is_active() else None


async def _build_story_timeline_decorator(
    db: AsyncSession,
    project_id: str,
    chapter: "Chapter",
) -> Optional[StoryTimelineDecorator]:
    """读取本章 + 上一章 expansion_plan 的时间锚字段,构造装饰器。

    第一章只有"本章锚",上一章字段缺失时只渲染本章。
    旧 expansion_plan 没有 story_time_* 字段时,装饰器整体跳过。
    """
    cur_anchor, cur_advance = _extract_time_fields(getattr(chapter, "expansion_plan", None))
    prev_anchor = ""
    if chapter.chapter_number > 1:
        from sqlalchemy import select
        from app.models.chapter import Chapter as _Chapter
        try:
            q = await db.execute(
                select(_Chapter.expansion_plan)
                .where(_Chapter.project_id == project_id)
                .where(_Chapter.chapter_number < chapter.chapter_number)
                .order_by(_Chapter.chapter_number.desc())
                .limit(1)
            )
            row = q.scalar_one_or_none()
            prev_anchor, _ = _extract_time_fields(row)
        except Exception as exc:
            logger.warning(f"⚠️ 上一章时间锚读取失败(跳过): {exc}")
    if not (cur_anchor or prev_anchor):
        return None
    return StoryTimelineDecorator(
        prev_anchor=prev_anchor,
        current_anchor=cur_anchor,
        advance=cur_advance,
    )


async def build_decorated_chapter_pipeline(
    *,
    db: AsyncSession,
    project: "Project",
    outline: Optional["Outline"],
    chapter: "Chapter",
    style_content: Optional[str],
    anti_ai_enabled: bool = True,
) -> PromptPipeline:
    """装配章节生成的 PromptPipeline（含契约 / 便签 / 风格模式 / 声音 / 意象 / 反 AI / 输出格式）。

    所有上下文准备均在此完成，调用方只需提交 base_prompt 即可。
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

    narrator_voice = _build_narrator_voice_decorator(project)
    motif_cooling = await _build_motif_cooling_decorator(
        db, project.id, chapter.chapter_number
    )
    fact_consistency = await _build_fact_consistency_decorator(db, project.id)
    character_arc = await _build_character_arc_decorator(
        db, project.id, chapter.chapter_number
    )
    location_variety = await _build_location_variety_decorator(
        db, project.id, chapter.chapter_number
    )
    plot_beat_cooling = await _build_plot_beat_cooling_decorator(
        db, project.id, chapter.chapter_number
    )
    story_timeline = await _build_story_timeline_decorator(
        db, project.id, chapter
    )
    pacing_milestone = _build_pacing_milestone_decorator(
        volume_brief, chapter.chapter_number
    )

    return PromptPipeline.for_chapter_generation(
        style_content=style_content,
        anti_ai_enabled=anti_ai_enabled,
        contract=project_contract,
        volume_brief=volume_brief,
        chapter_brief=chapter_brief,
        scratchpad_text=scratchpad_text,
        style_pattern_text=style_pattern_text,
        fact_consistency=fact_consistency,
        character_arc=character_arc,
        narrator_voice=narrator_voice,
        motif_cooling=motif_cooling,
        location_variety=location_variety,
        plot_beat_cooling=plot_beat_cooling,
        story_timeline=story_timeline,
        pacing_milestone=pacing_milestone,
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
