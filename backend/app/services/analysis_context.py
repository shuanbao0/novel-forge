"""章节分析上下文构造器 - 为 PlotAnalyzer 提供窗口上下文（前后章 + 大纲意图 + 历史评分基线）"""
import json
import re
from collections import Counter
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.outline import Outline
from app.models.memory import PlotAnalysis
from app.logger import get_logger

logger = get_logger(__name__)


def _safe_load_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def _query_neighbor_chapters(
    db: AsyncSession,
    project_id: str,
    current_chapter_number: int,
    before: int,
    after: int,
) -> Tuple[List[Chapter], List[Chapter]]:
    """一次查询当前章节前后的邻居章节"""
    prev_stmt = (
        select(Chapter)
        .where(
            and_(
                Chapter.project_id == project_id,
                Chapter.chapter_number < current_chapter_number,
            )
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(before)
    )
    next_stmt = (
        select(Chapter)
        .where(
            and_(
                Chapter.project_id == project_id,
                Chapter.chapter_number > current_chapter_number,
            )
        )
        .order_by(Chapter.chapter_number.asc())
        .limit(after)
    )
    prev_result = await db.execute(prev_stmt)
    next_result = await db.execute(next_stmt)
    prev_chapters = list(prev_result.scalars().all())
    next_chapters = list(next_result.scalars().all())
    prev_chapters.reverse()  # 按章节号升序返回，便于按时间顺序呈现给模型
    return prev_chapters, next_chapters


def _build_recent_summaries(prev_chapters: List[Chapter]) -> List[Dict[str, Any]]:
    out = []
    for ch in prev_chapters:
        summary = (ch.summary or '').strip()
        if not summary:
            # 没有摘要时退化为正文前 200 字，避免完全空缺
            content_head = (ch.content or '').strip()[:200]
            summary = content_head + ('…' if len(ch.content or '') > 200 else '')
        if not summary:
            continue
        out.append({
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "summary": summary,
        })
    return out


async def _build_chapter_intent(
    db: AsyncSession,
    chapter: Chapter,
) -> Dict[str, Any]:
    """汇总本章意图：expansion_plan + creative_brief + 关联 Outline 的 structure + volume brief"""
    intent: Dict[str, Any] = {}

    # 章级展开规划（1-N 模式）
    plan = _safe_load_json(chapter.expansion_plan)
    if plan:
        if plan.get('key_events'):
            intent['key_events'] = plan['key_events']
        if plan.get('character_focus'):
            intent['character_focus'] = plan['character_focus']
        if plan.get('emotional_tone'):
            intent['emotional_tone'] = plan['emotional_tone']

    # 章级契约
    brief = chapter.creative_brief or {}
    if isinstance(brief, dict):
        if brief.get('directive'):
            intent['directive'] = brief['directive']
        if brief.get('forbidden_zones'):
            intent['forbidden_zones'] = brief['forbidden_zones']

    # 关联大纲（1-1 模式或 1-N 模式的卷级）
    if chapter.outline_id:
        outline_result = await db.execute(
            select(Outline).where(Outline.id == chapter.outline_id)
        )
        outline = outline_result.scalar_one_or_none()
        if outline:
            structure = _safe_load_json(outline.structure)
            if structure:
                # 大纲结构里的关键事件/角色，仅在 expansion_plan 缺失时回填
                if 'key_events' not in intent and structure.get('key_events'):
                    intent['key_events'] = structure['key_events']
                if 'character_focus' not in intent and structure.get('characters'):
                    intent['character_focus'] = structure['characters']
                if 'emotional_tone' not in intent and structure.get('emotional_tone'):
                    intent['emotional_tone'] = structure['emotional_tone']
            if outline.content:
                intent['outline_text'] = outline.content
            vol_brief = outline.creative_brief or {}
            if isinstance(vol_brief, dict) and vol_brief.get('volume_goal'):
                intent['volume_goal'] = vol_brief['volume_goal']

    return intent


async def _build_upcoming_outline(
    db: AsyncSession,
    next_chapters: List[Chapter],
) -> List[Dict[str, Any]]:
    out = []
    for ch in next_chapters:
        intent_parts: List[str] = []
        plan = _safe_load_json(ch.expansion_plan)
        if plan:
            if plan.get('key_events'):
                events_text = '；'.join(
                    (ev.get('content') or ev.get('description') or str(ev))
                    if isinstance(ev, dict) else str(ev)
                    for ev in plan['key_events']
                )
                if events_text:
                    intent_parts.append(f"关键事件：{events_text}")
            if plan.get('emotional_tone'):
                intent_parts.append(f"情感基调：{plan['emotional_tone']}")
        # 退化到挂载大纲
        if not intent_parts and ch.outline_id:
            outline_result = await db.execute(
                select(Outline).where(Outline.id == ch.outline_id)
            )
            outline = outline_result.scalar_one_or_none()
            if outline and outline.content:
                intent_parts.append(outline.content.strip()[:300])
        # 退化到章节自身摘要
        if not intent_parts and (ch.summary or '').strip():
            intent_parts.append((ch.summary or '').strip())

        out.append({
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "intent": '\n'.join(intent_parts),
        })
    return out


_SUGGESTION_TAG_RE = re.compile(r'【([^】]{1,12})】')


async def _build_score_baseline(
    db: AsyncSession,
    project_id: str,
    current_chapter_number: int,
    window: int = 5,
) -> Dict[str, Any]:
    """
    P1: 构造历史评分基线 - 取本章之前最近 N 章已分析数据，计算各维度均值与高频建议标签。
    返回空 dict 表示样本不足（< 2 章），由模板按"无基线"分支处理。
    """
    if current_chapter_number <= 1:
        return {}

    stmt = (
        select(PlotAnalysis)
        .join(Chapter, Chapter.id == PlotAnalysis.chapter_id)
        .where(
            and_(
                PlotAnalysis.project_id == project_id,
                Chapter.chapter_number < current_chapter_number,
            )
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(window)
    )
    result = await db.execute(stmt)
    analyses = list(result.scalars().all())
    if len(analyses) < 2:
        return {}

    def _avg(values: List[Optional[float]]) -> Optional[float]:
        vals = [v for v in values if isinstance(v, (int, float))]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    overall_avg = _avg([a.overall_quality_score for a in analyses])
    pacing_avg = _avg([a.pacing_score for a in analyses])
    engagement_avg = _avg([a.engagement_score for a in analyses])
    coherence_avg = _avg([a.coherence_score for a in analyses])

    # 高频建议标签 - 形如 "【节奏问题】..."，提取方括号内 tag 做频次统计
    tag_counter: Counter = Counter()
    total_suggestions = 0
    for a in analyses:
        for s in (a.suggestions or []):
            if not isinstance(s, str):
                continue
            total_suggestions += 1
            for tag in _SUGGESTION_TAG_RE.findall(s):
                tag = tag.strip()
                if tag:
                    tag_counter[tag] += 1
    top_tags = tag_counter.most_common(5)

    # 评分波动幅度（极差）用于辅助判断"稳定 vs 漂移"
    overall_values = [a.overall_quality_score for a in analyses if a.overall_quality_score]
    overall_spread = (
        round(max(overall_values) - min(overall_values), 2)
        if len(overall_values) >= 2 else None
    )

    return {
        "sample_size": len(analyses),
        "averages": {
            "overall": overall_avg,
            "pacing": pacing_avg,
            "engagement": engagement_avg,
            "coherence": coherence_avg,
        },
        "overall_spread": overall_spread,
        "top_suggestion_tags": top_tags,
        "avg_suggestions_per_chapter": (
            round(total_suggestions / len(analyses), 1) if analyses else 0
        ),
    }


async def build_analysis_context(
    db: AsyncSession,
    project_id: str,
    chapter: Chapter,
    recent_n: int = 3,
    upcoming_n: int = 2,
    baseline_window: int = 5,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """
    构造章节分析的窗口上下文，返回 (recent_summaries, chapter_intent, upcoming_outline, score_baseline)。
    任一组件失败都不中断分析，最坏情况下返回空结构，由 PlotAnalyzer 输出友好默认文案。
    """
    try:
        prev_chapters, next_chapters = await _query_neighbor_chapters(
            db, project_id, chapter.chapter_number, recent_n, upcoming_n
        )
    except Exception as e:
        logger.warning(f"⚠️ 查询邻居章节失败，分析将退化为无窗口上下文: {e}")
        return [], {}, [], {}

    recent_summaries = _build_recent_summaries(prev_chapters)

    try:
        chapter_intent = await _build_chapter_intent(db, chapter)
    except Exception as e:
        logger.warning(f"⚠️ 构造本章意图失败: {e}")
        chapter_intent = {}

    try:
        upcoming_outline = await _build_upcoming_outline(db, next_chapters)
    except Exception as e:
        logger.warning(f"⚠️ 构造后续章节梗概失败: {e}")
        upcoming_outline = []

    try:
        score_baseline = await _build_score_baseline(
            db, project_id, chapter.chapter_number, baseline_window
        )
    except Exception as e:
        logger.warning(f"⚠️ 构造历史评分基线失败: {e}")
        score_baseline = {}

    logger.info(
        f"📋 分析上下文构造完成: 前序章节={len(recent_summaries)}, "
        f"本章意图字段={len(chapter_intent)}, 后续章节={len(upcoming_outline)}, "
        f"基线样本={score_baseline.get('sample_size', 0)}"
    )
    return recent_summaries, chapter_intent, upcoming_outline, score_baseline
