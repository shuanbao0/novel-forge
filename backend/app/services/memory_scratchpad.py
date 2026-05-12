"""记忆便签 - 借鉴 webnovel-writer memory_scratchpad.json

把已有的 StoryMemory / Foreshadow / 角色当前状态压缩成一段简短文本,
供审稿器和后续章节生成时快速参考(避免每次重查多张表)。

设计:
- 是一个聚合视图,不创建新表
- 每次调用即时计算(成本低)
- 输出文本长度控制在 1500 字符内,适合 prompt 注入
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    pass


@dataclass
class Scratchpad:
    recent_events: list[str] = field(default_factory=list)
    active_foreshadows: list[str] = field(default_factory=list)
    key_world_rules: list[str] = field(default_factory=list)
    character_states: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.recent_events or self.active_foreshadows
            or self.key_world_rules or self.character_states
        )

    def to_prompt_text(self, max_chars: int = 1500) -> str:
        """渲染成简短便签文本"""
        if self.is_empty():
            return ""
        parts: list[str] = ["【📝 记忆便签 - 当前剧情快照】"]
        if self.recent_events:
            parts.append("\n## 最近事件")
            parts.extend(f"- {e}" for e in self.recent_events)
        if self.character_states:
            parts.append("\n## 角色当前状态")
            parts.extend(f"- {s}" for s in self.character_states)
        if self.active_foreshadows:
            parts.append("\n## 已埋未收的伏笔")
            parts.extend(f"- {f}" for f in self.active_foreshadows)
        if self.key_world_rules:
            parts.append("\n## 关键世界规则")
            parts.extend(f"- {r}" for r in self.key_world_rules)
        text = "\n".join(parts)
        return text[:max_chars] + ("..." if len(text) > max_chars else "")


async def build_scratchpad(
    db: AsyncSession,
    project_id: str,
    *,
    recent_chapters: int = 3,
    max_foreshadows: int = 8,
) -> Scratchpad:
    """从 DB 装配便签

    取最近 N 章的剧情要点 + 活跃伏笔 + 项目世界规则。
    任意环节失败不影响其他环节(尽力而为)。
    """
    pad = Scratchpad()

    # 最近事件 - 用 StoryMemory 里 importance>=0.6 的 plot_point
    try:
        from app.models.memory import StoryMemory
        result = await db.execute(
            select(StoryMemory)
            .where(StoryMemory.project_id == project_id)
            .where(StoryMemory.memory_type.in_(["plot_point", "character_event"]))
            .order_by(desc(StoryMemory.created_at))
            .limit(6)
        )
        for m in result.scalars().all():
            title = (m.title or m.content or "").strip()
            if title:
                pad.recent_events.append(title[:120])
    except Exception:
        pass

    # 活跃伏笔(planted 状态)
    try:
        from app.models.foreshadow import Foreshadow
        result = await db.execute(
            select(Foreshadow)
            .where(Foreshadow.project_id == project_id)
            .where(Foreshadow.status == "planted")
            .order_by(desc(Foreshadow.importance))
            .limit(max_foreshadows)
        )
        for f in result.scalars().all():
            tag = f.title or (f.content or "")[:40]
            chapter_info = f"(第{f.plant_chapter_number}章埋)" if f.plant_chapter_number else ""
            pad.active_foreshadows.append(f"{tag}{chapter_info}")
    except Exception:
        pass

    # 关键世界规则 - 从 Project 抽取
    try:
        from app.models.project import Project
        project = await db.get(Project, project_id)
        if project and project.world_rules:
            rules_text = (project.world_rules or "").strip()
            if rules_text:
                # 按行/句号分,取前 3 条
                lines = [
                    line.strip() for line in rules_text.replace("。", "\n").split("\n")
                    if line.strip()
                ]
                pad.key_world_rules.extend(lines[:3])
    except Exception:
        pass

    return pad
