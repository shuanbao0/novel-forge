"""蓝图验证关 - 阶段 6 LLM 产出 expansion_plan 后, 落库前必跑

问题背景:
- 阶段 5 OUTLINE_CREATE 生成抽象大纲节点(例:"高三晚自习重生开篇")
- 阶段 6 OUTLINE_EXPAND_MULTI 把单节点展开成 N 章 chapter_plans
- 旧 prompt 鼓励"放慢节奏不要快速推进", LLM 合规地把 10 章全部塞进同一场景同一时段
  → 章节生成阶段(7c)的 StoryTimelineDecorator 只是把"紧接上章"重复贯彻, 越修越死

修复策略(Strategy + Chain of Responsibility):
- 多条规则各管一个维度(场景多样性 / 时间推进 / 事件骨架去重)
- 任一规则报错都进入"重试"路径(由上层 PlotExpansionService 负责)
- 规则无副作用, 不修改 plans, 只读校验
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol

from app.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ValidationError:
    rule: str
    detail: str
    offender_indices: list[int] = field(default_factory=list)

    def to_feedback_line(self) -> str:
        loc = (
            f" (违规章序: {', '.join(str(i + 1) for i in self.offender_indices)})"
            if self.offender_indices else ""
        )
        return f"- [{self.rule}] {self.detail}{loc}"


class BlueprintRejected(Exception):
    """蓝图被验证关拒收时抛出, 由上层捕获并执行重试."""

    def __init__(self, errors: list[ValidationError]):
        super().__init__("; ".join(e.detail for e in errors))
        self.errors = errors

    def to_feedback_block(self) -> str:
        """渲染成可注入 LLM 的反馈块, 用于重试时告诉 LLM 上轮哪里被拒."""
        lines = ["【🚫 上一轮蓝图被验证关拒收, 本轮必须修复以下问题】"]
        lines.extend(e.to_feedback_line() for e in self.errors)
        return "\n".join(lines)


class BlueprintRule(Protocol):
    """蓝图校验规则协议. 实现类只读检查, 不修改 plans."""

    name: str

    def validate(self, plans: list[dict]) -> list[ValidationError]:
        ...


class SceneVarietyRule:
    """主场景必须切换 ≥ ⌈N/3⌉ 次.

    例 10 章: 至少 4 个不同主场景; 全部"教室晚自习"就会被拒.
    每章主场景取自:
      1. scenes[0].location  (首选, 若 LLM 按 OUTLINE_EXPAND 模板填了 scenes)
      2. plot_summary 里第一个出现的"地点"关键词 (兜底, 但目前模板未要求, 忽略)
      3. 直接降级为 ""(空), 算作"未指定", 不参与统计
    """

    name = "scene_variety"
    MIN_CHAPTERS = 3  # 少于 3 章不触发(单章/双章本就难拆场景)

    def validate(self, plans: list[dict]) -> list[ValidationError]:
        n = len(plans)
        if n < self.MIN_CHAPTERS:
            return []
        threshold = math.ceil(n / 3)
        locations: list[str] = []
        for p in plans:
            loc = ""
            scenes = p.get("scenes") if isinstance(p, dict) else None
            if isinstance(scenes, list) and scenes and isinstance(scenes[0], dict):
                loc = (scenes[0].get("location") or "").strip()
            locations.append(loc)
        named = [l for l in locations if l]
        unique = len(set(named))
        if unique >= threshold:
            return []
        # 找到重复最多的那个场景对应的章节下标, 作为违规清单
        from collections import Counter
        if not named:
            return [ValidationError(
                self.name,
                f"{n} 章全部未填 scenes[0].location, 无法验证场景多样性",
            )]
        most_common, _ = Counter(named).most_common(1)[0]
        offenders = [i for i, l in enumerate(locations) if l == most_common]
        return [ValidationError(
            self.name,
            (f"{n} 章只覆盖 {unique} 个主场景(要求 ≥ {threshold}), "
             f"主场景 '{most_common}' 被复用 {len(offenders)} 次"),
            offender_indices=offenders,
        )]


class TimeAdvanceRule:
    """story_time_advance 不能让多数章节都"紧接上章".

    允许少量章节紧接(同一场戏的不同段落), 但超过 2/3 章数则视为"故事内时间零推进".
    """

    name = "time_advance"
    SOFT_WORDS = ("紧接", "同一", "立刻", "随即", "片刻", "稍后")
    MIN_CHAPTERS = 4
    SOFT_RATIO_LIMIT = 2 / 3  # 紧接类章数占比 > 此值即拒

    def validate(self, plans: list[dict]) -> list[ValidationError]:
        n = len(plans)
        if n < self.MIN_CHAPTERS:
            return []
        soft_idx: list[int] = []
        for i, p in enumerate(plans):
            adv = (p.get("story_time_advance") or "").strip() if isinstance(p, dict) else ""
            if any(w in adv for w in self.SOFT_WORDS):
                soft_idx.append(i)
        if len(soft_idx) <= n * self.SOFT_RATIO_LIMIT:
            return []
        return [ValidationError(
            self.name,
            (f"{len(soft_idx)}/{n} 章的 story_time_advance 为'紧接上章'类, "
             f"故事内时间几乎零推进(上限 {self.SOFT_RATIO_LIMIT:.0%})"),
            offender_indices=soft_idx,
        )]


class KeyEventSkeletonRule:
    """跨章 key_events 高度同骨架视为复读.

    简化骨架: 对每章把 key_events 串成短语集合, 两章 Jaccard 相似度 ≥ JACCARD_LIMIT
    视为同骨架; 若 ≥ 半数对都同骨架 → 触发.
    更精细的"动词+角色"提取留给阶段 7f scene_skeleton 反馈环路, 这里只做粗筛.
    """

    name = "key_event_skeleton"
    MIN_CHAPTERS = 4
    JACCARD_LIMIT = 0.5

    def _tokens(self, key_events) -> set[str]:
        if not isinstance(key_events, list):
            return set()
        tokens: set[str] = set()
        for e in key_events:
            if not isinstance(e, str):
                continue
            s = e.strip()
            if len(s) >= 3:
                tokens.add(s)
        return tokens

    def _jaccard(self, a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def validate(self, plans: list[dict]) -> list[ValidationError]:
        n = len(plans)
        if n < self.MIN_CHAPTERS:
            return []
        token_sets = [self._tokens(p.get("key_events") if isinstance(p, dict) else None)
                      for p in plans]
        if not any(token_sets):
            return []
        offenders: set[int] = set()
        for i in range(n):
            for j in range(i + 1, n):
                if self._jaccard(token_sets[i], token_sets[j]) >= self.JACCARD_LIMIT:
                    offenders.add(i)
                    offenders.add(j)
        # 触发阈值: 一半以上章节卷入复读对
        if len(offenders) <= n // 2:
            return []
        return [ValidationError(
            self.name,
            (f"{len(offenders)}/{n} 章的 key_events 与至少一个其他章 "
             f"Jaccard 相似度 ≥ {self.JACCARD_LIMIT:.0%}, 桥段高度复读"),
            offender_indices=sorted(offenders),
        )]


class BlueprintValidator:
    """规则编排入口. 按注册顺序逐条跑, 收集所有 errors 一次性抛出.

    一次性收集而非首条短路, 让 LLM 在重试时能看到全部违规, 一次性修复.
    """

    DEFAULT_RULES: tuple[BlueprintRule, ...] = (
        SceneVarietyRule(),
        TimeAdvanceRule(),
        KeyEventSkeletonRule(),
    )

    def __init__(self, rules: tuple[BlueprintRule, ...] | None = None):
        self._rules = rules or self.DEFAULT_RULES

    def validate(self, plans: list[dict]) -> list[ValidationError]:
        if not plans:
            return []
        errors: list[ValidationError] = []
        for rule in self._rules:
            try:
                errors.extend(rule.validate(plans))
            except Exception as exc:
                logger.warning(f"⚠️ 蓝图规则 {rule.name} 内部异常(跳过该规则): {exc}")
        return errors

    def check(self, plans: list[dict]) -> None:
        """有任一错误即抛出 BlueprintRejected, 上层据此决定重试."""
        errors = self.validate(plans)
        if errors:
            raise BlueprintRejected(errors)


def validate_project_blueprint(
    outline_id_to_plans: dict[str, list[dict]],
) -> list[ValidationError]:
    """跨大纲节点的项目级"全局多样性"检查.

    单 outline 内的 SceneVarietyRule 不能发现"3 个大纲节点各 4 章, 各自内部都通过,
    但 12 章全在晚自习"这类场景塌缩. 本函数对整个项目跑一次合并视图.

    阈值: 项目内总章数 ≥ 6 时, 主场景独立值至少 ⌈total/4⌉
    (比单批 ⌈N/3⌉ 略宽松, 因为跨段允许有重复主场景 — 例如多章回学校).

    无入参 / 总章 < 6 / 仅 1 个 outline 时返回空, 不强加约束.
    """
    if not outline_id_to_plans or len(outline_id_to_plans) < 2:
        return []
    all_plans: list[dict] = []
    for plans in outline_id_to_plans.values():
        if isinstance(plans, list):
            all_plans.extend(plans)
    total = len(all_plans)
    if total < 6:
        return []
    locations: list[str] = []
    for p in all_plans:
        scenes = p.get("scenes") if isinstance(p, dict) else None
        if isinstance(scenes, list) and scenes and isinstance(scenes[0], dict):
            locations.append((scenes[0].get("location") or "").strip())
        else:
            locations.append("")
    named = [l for l in locations if l]
    if not named:
        return [ValidationError(
            "project_scene_variety",
            f"项目共 {total} 章全部未填 scenes[0].location, 无法验证跨大纲多样性",
        )]
    import math
    from collections import Counter
    threshold = math.ceil(total / 4)
    unique = len(set(named))
    if unique >= threshold:
        return []
    most_common, hit = Counter(named).most_common(1)[0]
    offenders = [i for i, l in enumerate(locations) if l == most_common]
    return [ValidationError(
        "project_scene_variety",
        (f"跨大纲合计 {total} 章只覆盖 {unique} 个主场景(项目级要求 ≥ {threshold}), "
         f"主场景 '{most_common}' 在不同大纲间被重复 {hit} 次, 全书原地踏步"),
        offender_indices=offenders,
    )]
