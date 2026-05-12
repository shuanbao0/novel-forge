"""数据抽取器 - 借鉴 webnovel-writer data-agent 的标准化事件类型

事件类型(8 种):
- character_state_changed: 角色状态变化(情绪/伤势/位置)
- power_breakthrough: 实力突破(等级提升/获得新能力)
- relationship_changed: 关系变化(亲密度/敌对/背叛)
- world_rule_revealed: 揭示了一条世界规则
- world_rule_broken: 违反/挑战了一条世界规则
- open_loop_created: 创建了一个未解决的悬念
- open_loop_closed: 闭合了一个旧悬念
- promise_created: 创建了一条读者承诺
- promise_paid_off: 兑现了一条读者承诺
- artifact_obtained: 获得了一件关键物品

与 webnovel-writer 不同:本实现是结构化标记 + 简单规则抽取,
不依赖 LLM 二次调用,而是从 PlotAnalysis 的现有 JSON 字段映射出来。
后续可扩展为 LLM 抽取以提升精度。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class EventType(str, Enum):
    CHARACTER_STATE_CHANGED = "character_state_changed"
    POWER_BREAKTHROUGH = "power_breakthrough"
    RELATIONSHIP_CHANGED = "relationship_changed"
    WORLD_RULE_REVEALED = "world_rule_revealed"
    WORLD_RULE_BROKEN = "world_rule_broken"
    OPEN_LOOP_CREATED = "open_loop_created"
    OPEN_LOOP_CLOSED = "open_loop_closed"
    PROMISE_CREATED = "promise_created"
    PROMISE_PAID_OFF = "promise_paid_off"
    ARTIFACT_OBTAINED = "artifact_obtained"


@dataclass
class ExtractedEvent:
    type: EventType
    summary: str = ""
    actors: list[str] = field(default_factory=list)
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "summary": self.summary,
            "actors": self.actors,
            "evidence": self.evidence,
        }


# 关键词触发规则 - 关键字命中即推断事件类型
# 字典是有序的:同一段文本只取第一个命中的类型,避免重复
_KEYWORD_RULES: list[tuple[EventType, list[str]]] = [
    (EventType.POWER_BREAKTHROUGH, ["突破", "晋级", "进阶", "顿悟", "破境", "圆满", "等级提升"]),
    (EventType.ARTIFACT_OBTAINED, ["获得", "得到了", "拾起了", "拿到了", "捡到了", "继承了"]),
    (EventType.RELATIONSHIP_CHANGED, ["反目", "决裂", "结盟", "结义", "拜师", "认主", "翻脸", "和好", "背叛"]),
    (EventType.WORLD_RULE_BROKEN, ["违反", "破坏", "打破了规矩", "违背禁忌"]),
    (EventType.WORLD_RULE_REVEALED, ["原来", "事实是", "真相是", "规则是", "传说"]),
    (EventType.PROMISE_PAID_OFF, ["报仇了", "兑现", "完成了诺言", "终于做到"]),
    (EventType.PROMISE_CREATED, ["立誓", "发誓", "承诺", "约定", "决心要"]),
    (EventType.OPEN_LOOP_CLOSED, ["谜底揭开", "真相大白", "终于明白"]),
]


def extract_events_from_analysis(analysis: dict) -> list[ExtractedEvent]:
    """从 PlotAnalysis 结果映射标准事件

    输入: PlotAnalysis 字典(含 hooks/foreshadows/character_events/important_events)
    输出: ExtractedEvent 列表
    """
    if not isinstance(analysis, dict):
        return []

    events: list[ExtractedEvent] = []

    # 1. 钩子(hooks) → open_loop_created
    for hook in _safe_list(analysis.get("hooks")):
        events.append(ExtractedEvent(
            type=EventType.OPEN_LOOP_CREATED,
            summary=str(hook.get("description", "") or hook.get("content", ""))[:200],
            evidence=str(hook.get("evidence", ""))[:200],
        ))

    # 2. 伏笔(foreshadows) → promise_created
    for fs in _safe_list(analysis.get("foreshadows")):
        events.append(ExtractedEvent(
            type=EventType.PROMISE_CREATED,
            summary=str(fs.get("content", "") or fs.get("description", ""))[:200],
            actors=_safe_str_list(fs.get("related_characters")),
        ))

    # 3. 角色事件(character_events) → character_state_changed
    for ev in _safe_list(analysis.get("character_events")):
        events.append(ExtractedEvent(
            type=EventType.CHARACTER_STATE_CHANGED,
            summary=str(ev.get("event", "") or ev.get("description", ""))[:200],
            actors=_safe_str_list(ev.get("character") or ev.get("characters")),
        ))

    # 4. 重要事件(important_events) → 走关键词规则细分
    for ev in _safe_list(analysis.get("important_events")):
        text = str(ev.get("description", "") or ev.get("content", "")).strip()
        if not text:
            continue
        ev_type = _detect_event_type(text) or EventType.CHARACTER_STATE_CHANGED
        events.append(ExtractedEvent(
            type=ev_type,
            summary=text[:200],
            actors=_safe_str_list(ev.get("characters")),
        ))

    return events


def extract_events_from_text(text: str, max_events: int = 10) -> list[ExtractedEvent]:
    """从纯正文做关键词级抽取(辅助/兜底,精度有限)

    把内容按段落 + 中文句号分割,每个句子判定一次主要事件类型。
    """
    if not text:
        return []
    # 同时按段落和句号分,以便单段多事件能被发现
    chunks: list[str] = []
    for para in re.split(r"\n+", text):
        para = para.strip()
        if not para:
            continue
        for sent in re.split(r"[。!?！?]+", para):
            sent = sent.strip()
            if sent:
                chunks.append(sent)
    events: list[ExtractedEvent] = []
    for sent in chunks:
        ev_type = _detect_event_type(sent)
        if ev_type:
            events.append(ExtractedEvent(
                type=ev_type,
                summary=sent[:120],
                evidence=sent[:200],
            ))
            if len(events) >= max_events:
                break
    return events


def _detect_event_type(text: str) -> EventType | None:
    for ev_type, keywords in _KEYWORD_RULES:
        for kw in keywords:
            if kw in text:
                return ev_type
    return None


def _safe_list(value: Any) -> Iterable[dict]:
    if isinstance(value, list):
        return (v for v in value if isinstance(v, dict))
    return []


def _safe_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []
