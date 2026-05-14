"""创作契约 - 借鉴 webnovel-writer MASTER_SETTING / VolumeBrief / ChapterBrief

把"全局硬约束"沉淀为可重用的数据结构,通过 Decorator 注入到章节生成 prompt。
契约不是状态源(DB 行才是),它只是约束声明。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CreativeContract:
    """章节生成的全局硬约束

    所有字段都是可选;空字段会被装饰器跳过。
    """
    # 风格底线(必须保持的写作风格特征,跨整本书一致)
    style_baseline: str = ""

    # 禁忌区(明确禁止出现的情节/桥段/设定)
    forbidden_zones: list[str] = field(default_factory=list)

    # 反模式(应避免的写作套路)
    anti_patterns: list[str] = field(default_factory=list)

    # 必备桥段(本书类型要求必须包含的元素)
    required_tropes: list[str] = field(default_factory=list)

    # 读者承诺(向读者隐含承诺的剧情终点,例如"主角必须打败大反派")
    narrative_promises: list[str] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Optional[Any]) -> "CreativeContract":
        """从 DB 中的 JSON 列还原契约,兼容 None / dict / 其他"""
        if not isinstance(raw, dict):
            return cls()
        return cls(
            style_baseline=str(raw.get("style_baseline", "") or "").strip(),
            forbidden_zones=_as_str_list(raw.get("forbidden_zones")),
            anti_patterns=_as_str_list(raw.get("anti_patterns")),
            required_tropes=_as_str_list(raw.get("required_tropes")),
            narrative_promises=_as_str_list(raw.get("narrative_promises")),
        )

    def to_dict(self) -> dict:
        return {
            "style_baseline": self.style_baseline,
            "forbidden_zones": self.forbidden_zones,
            "anti_patterns": self.anti_patterns,
            "required_tropes": self.required_tropes,
            "narrative_promises": self.narrative_promises,
        }

    def is_empty(self) -> bool:
        return not (
            self.style_baseline
            or self.forbidden_zones
            or self.anti_patterns
            or self.required_tropes
            or self.narrative_promises
        )

    def to_prompt_block(self) -> str:
        """生成可注入 system prompt 的契约说明块(空契约返回空串)"""
        if self.is_empty():
            return ""

        sections: list[str] = ["【📜 创作契约 - 全局硬约束】"]

        if self.style_baseline:
            sections.append(f"\n## 风格底线\n{self.style_baseline}")

        if self.forbidden_zones:
            sections.append("\n## 禁忌区(以下情节/设定严禁出现)")
            sections.extend(f"❌ {item}" for item in self.forbidden_zones)

        if self.anti_patterns:
            sections.append("\n## 反模式(以下写作套路严禁使用)")
            sections.extend(f"❌ {item}" for item in self.anti_patterns)

        if self.required_tropes:
            sections.append("\n## 必备桥段(本书类型要求)")
            sections.extend(f"✅ {item}" for item in self.required_tropes)

        if self.narrative_promises:
            sections.append("\n## 读者承诺(剧情必须服务于以下长线目标)")
            sections.extend(f"🎯 {item}" for item in self.narrative_promises)

        return "\n".join(sections)


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _as_milestone_list(value: Any) -> list[dict]:
    """归一化 pacing_milestones 输入为 [{by_chapter:int, milestone:str}, ...].

    输入容错:
      - 不是 list / dict → 返回 []
      - 单个 dict 缺字段或字段类型错 → 静默跳过
      - by_chapter 可能是数字字符串 → 强制 int,失败跳过
    """
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        by_raw = item.get("by_chapter")
        text = (item.get("milestone") or "").strip() if isinstance(item.get("milestone"), str) else ""
        if not text:
            continue
        try:
            by = int(by_raw)
        except (TypeError, ValueError):
            continue
        if by <= 0:
            continue
        out.append({"by_chapter": by, "milestone": text})
    out.sort(key=lambda x: x["by_chapter"])
    return out


@dataclass
class VolumeBrief:
    """卷级契约 - 作用于挂在某 Outline 下的所有章节

    与 CreativeContract 的关系:同一项目下,Volume 级覆盖 Project 级。
    """
    volume_goal: str = ""           # 本卷的叙事目标
    anti_patterns: list[str] = field(default_factory=list)
    required_tropes: list[str] = field(default_factory=list)
    pacing: str = ""                # 本卷期望节奏(快/平稳/紧凑)
    pacing_milestones: list[dict] = field(default_factory=list)
    """节奏里程碑 - [{"by_chapter": int, "milestone": str}, ...]
    用法:
      - 规划阶段(plot_expansion): 渲染进 prompt,让 LLM 按里程碑分配章节字数
      - 生成阶段(PacingMilestoneDecorator): 把"逾期/即将到期"塞进 system_prompt
    """

    @classmethod
    def from_raw(cls, raw: Optional[Any]) -> "VolumeBrief":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            volume_goal=str(raw.get("volume_goal", "") or "").strip(),
            anti_patterns=_as_str_list(raw.get("anti_patterns")),
            required_tropes=_as_str_list(raw.get("required_tropes")),
            pacing=str(raw.get("pacing", "") or "").strip(),
            pacing_milestones=_as_milestone_list(raw.get("pacing_milestones")),
        )

    def is_empty(self) -> bool:
        return not (
            self.volume_goal or self.anti_patterns or self.required_tropes
            or self.pacing or self.pacing_milestones
        )

    def to_prompt_block(self) -> str:
        if self.is_empty():
            return ""
        sections = ["【📘 本卷契约 - 卷级约束(优先级高于项目级)】"]
        if self.volume_goal:
            sections.append(f"\n## 本卷目标\n{self.volume_goal}")
        if self.pacing:
            sections.append(f"\n## 期望节奏\n{self.pacing}")
        if self.pacing_milestones:
            sections.append("\n## 节奏里程碑(规划必须按此推进)")
            for m in self.pacing_milestones:
                sections.append(f"- 第 {m['by_chapter']} 章前: {m['milestone']}")
        if self.anti_patterns:
            sections.append("\n## 本卷反模式")
            sections.extend(f"❌ {p}" for p in self.anti_patterns)
        if self.required_tropes:
            sections.append("\n## 本卷必备桥段")
            sections.extend(f"✅ {t}" for t in self.required_tropes)
        return "\n".join(sections)


@dataclass
class ChapterBrief:
    """章级契约 - 作用于单章

    最高粒度的局部约束;优先级 章 > 卷 > 项目。
    """
    directive: str = ""                          # 本章核心指令
    forbidden_zones: list[str] = field(default_factory=list)
    must_check_nodes: list[str] = field(default_factory=list)  # 本章必须覆盖的节点

    @classmethod
    def from_raw(cls, raw: Optional[Any]) -> "ChapterBrief":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            directive=str(raw.get("directive", "") or "").strip(),
            forbidden_zones=_as_str_list(raw.get("forbidden_zones")),
            must_check_nodes=_as_str_list(raw.get("must_check_nodes")),
        )

    def is_empty(self) -> bool:
        return not (self.directive or self.forbidden_zones or self.must_check_nodes)

    def to_prompt_block(self) -> str:
        if self.is_empty():
            return ""
        sections = ["【📄 本章契约 - 章级约束(最高优先级)】"]
        if self.directive:
            sections.append(f"\n## 本章核心指令\n{self.directive}")
        if self.must_check_nodes:
            sections.append("\n## 本章必须覆盖")
            sections.extend(f"⭐ {n}" for n in self.must_check_nodes)
        if self.forbidden_zones:
            sections.append("\n## 本章禁忌(在常规禁忌之外额外的)")
            sections.extend(f"❌ {z}" for z in self.forbidden_zones)
        return "\n".join(sections)
