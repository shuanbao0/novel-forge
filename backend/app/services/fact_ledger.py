"""事实台账 - 跨章保持数值/身份/物品/关系的一致性

问题背景:
- 阶段 7b 上下文构建只把上一章末 500 字 + 摘要 300 字 + key_events[:5] 喂给下一章
- 这是自由文本, LLM 看到"数学 48"恰好出现在显眼位置就记住, 但"英语 53"出现在中段,
  几章之后就漂移成"英语 70+"
- 没有结构化事实, 向量记忆做的是语义检索而非精确查找, 数值类事实必然失真

修复策略(Value Object + Merge):
- FactLedger: 把"数值/身份/物品/关系"四类容易漂移的事实结构化存储
- FactDeltas: 单章产出, 由 PLOT_ANALYSIS 模板的 character_states[i].fact_deltas 字段提供
  (不另调 LLM, 复用已有的分析输出)
- merge(): 默认"已存在不覆盖", 防止 LLM 偶发抽错把对的数值改成错的;
  显式 force_overwrite=True 时才接受新值(例如分数从二模 → 三模 → 高考真实分)
- 仓储侧复用 StoryMemory(memory_type='fact_ledger'), 零 alembic 迁移
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# fact_deltas 里允许 LLM 标记本字段"应该覆盖旧值", 但默认 False(保守)
_FORCE_OVERWRITE_KEY = "force_overwrite"


@dataclass
class CharacterFacts:
    """单个角色的结构化事实快照."""
    scores: dict[str, float] = field(default_factory=dict)
    """数值类事实: {"高考数学": 48, "月薪": 3000} - 键名必须具体, 不要写"成绩"."""

    inventory: list[str] = field(default_factory=list)
    """物品类事实: ["旧诺基亚", "账本草稿纸"] - 长期持有的, 不记录消耗品."""

    identities: list[str] = field(default_factory=list)
    """身份/职位: ["云江三中高三七班", "云川时代创始人"] - 长期/阶段性身份."""

    relationships: dict[str, str] = field(default_factory=dict)
    """关系状态: {"韩宇": "对立", "赵启航": "信任"} - 单一关键词描述."""

    def is_empty(self) -> bool:
        return not (self.scores or self.inventory or self.identities or self.relationships)

    def to_lines(self, name: str) -> list[str]:
        """渲染成 prompt 块的若干行(不含表头)."""
        if self.is_empty():
            return []
        out = [f"## {name}"]
        if self.scores:
            out.append("- 分数: " + " / ".join(
                f"{k}={_fmt_score(v)}" for k, v in self.scores.items()
            ))
        if self.identities:
            out.append("- 身份: " + "、".join(self.identities))
        if self.inventory:
            out.append("- 物品: " + "、".join(self.inventory))
        if self.relationships:
            out.append("- 关系: " + "、".join(f"{k}({v})" for k, v in self.relationships.items()))
        return out


@dataclass
class FactLedger:
    """整本书的事实台账.

    单 project 单台账; 仓储侧只保留一行 StoryMemory.
    """
    project_id: str
    last_chapter_number: int = 0
    by_character: dict[str, CharacterFacts] = field(default_factory=dict)
    """key = 角色 name (不用 character.id, 因为 LLM 抽取时只知道名字)."""

    world: dict[str, str] = field(default_factory=dict)
    """世界级事实: {"date_anchor": "2008-05-10", "location_anchor": "云江市"}."""

    def merge(self, deltas: "FactDeltas") -> None:
        """把单章 deltas 合进台账.

        默认"已存在不覆盖", deltas 里显式 force_overwrite=True 才覆盖.
        新角色直接加入; 已存在角色 set 字段做并集, dict 字段做更新.
        """
        for name, char_delta in deltas.character_deltas.items():
            cur = self.by_character.setdefault(name, CharacterFacts())
            force = bool(char_delta.get(_FORCE_OVERWRITE_KEY))
            new_scores = _coerce_score_dict(char_delta.get("scores"))
            for k, v in new_scores.items():
                if force or k not in cur.scores:
                    cur.scores[k] = v
            new_inv = _coerce_str_list(char_delta.get("inventory"))
            cur.inventory = _merge_unique(cur.inventory, new_inv)
            new_ids = _coerce_str_list(char_delta.get("identities"))
            cur.identities = _merge_unique(cur.identities, new_ids)
            new_rel = _coerce_str_dict(char_delta.get("relationships"))
            cur.relationships.update(new_rel)
        for k, v in (deltas.world or {}).items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                self.world[k] = v.strip()

    def is_empty(self) -> bool:
        return not (self.world or any(not f.is_empty() for f in self.by_character.values()))

    def to_prompt_block(self) -> str:
        """渲染成 prompt 注入块, 空台账返回空串(装饰器据此跳过)."""
        if self.is_empty():
            return ""
        lines = ["【🧾 事实台账 - 已确定数值/身份, 本章涉及时必须沿用】"]
        if self.world:
            lines.append("## 世界")
            for k, v in self.world.items():
                lines.append(f"- {k}: {v}")
        for name, facts in self.by_character.items():
            lines.extend(facts.to_lines(name))
        lines.append(
            "❌ 严禁本章出现与上述事实矛盾的描写"
            "(尤其是数值字段, 例如分数/年龄/金钱)."
        )
        return "\n".join(lines)

    # === 序列化 ===
    def to_json(self) -> str:
        return json.dumps(
            {
                "last_chapter_number": self.last_chapter_number,
                "by_character": {n: asdict(f) for n, f in self.by_character.items()},
                "world": self.world,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, project_id: str, raw: Optional[str]) -> "FactLedger":
        if not raw:
            return cls(project_id=project_id)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls(project_id=project_id)
        if not isinstance(data, dict):
            return cls(project_id=project_id)
        by_char: dict[str, CharacterFacts] = {}
        for name, val in (data.get("by_character") or {}).items():
            if isinstance(name, str) and isinstance(val, dict):
                by_char[name] = CharacterFacts(
                    scores=_coerce_score_dict(val.get("scores")),
                    inventory=_coerce_str_list(val.get("inventory")),
                    identities=_coerce_str_list(val.get("identities")),
                    relationships=_coerce_str_dict(val.get("relationships")),
                )
        return cls(
            project_id=project_id,
            last_chapter_number=int(data.get("last_chapter_number") or 0),
            by_character=by_char,
            world=_coerce_str_dict(data.get("world")),
        )


@dataclass
class FactDeltas:
    """单章产出的事实增量, 由 PLOT_ANALYSIS character_states[i].fact_deltas 拼装."""
    character_deltas: dict[str, dict[str, Any]] = field(default_factory=dict)
    """key = 角色名, value = {scores, inventory, identities, relationships, force_overwrite}."""

    world: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.character_deltas or self.world)

    @classmethod
    def from_character_states(
        cls,
        character_states: Optional[list],
    ) -> "FactDeltas":
        """从 PlotAnalysis.character_states 列拼装.

        每个 character_state 形如:
          {"character_name": "林川",
           "fact_deltas": {
              "scores": {"高考数学": 48},
              "inventory": ["旧练习册"],
              "identities": ["云江三中高三七班"],
              "relationships": {"韩宇": "对立"},
              "force_overwrite": false  # 可选
           }}
        缺 fact_deltas 字段则忽略, 全本扫描下来若无任何 fact_deltas 会得到空对象,
        ExtractFactStateHook 据此跳过整个台账更新.
        """
        result = cls()
        if not isinstance(character_states, list):
            return result
        for cs in character_states:
            if not isinstance(cs, dict):
                continue
            name = (cs.get("character_name") or "").strip()
            fd = cs.get("fact_deltas")
            if not name or not isinstance(fd, dict):
                continue
            cleaned: dict[str, Any] = {}
            if isinstance(fd.get("scores"), dict):
                cleaned["scores"] = fd["scores"]
            if isinstance(fd.get("inventory"), list):
                cleaned["inventory"] = fd["inventory"]
            if isinstance(fd.get("identities"), list):
                cleaned["identities"] = fd["identities"]
            if isinstance(fd.get("relationships"), dict):
                cleaned["relationships"] = fd["relationships"]
            if _FORCE_OVERWRITE_KEY in fd:
                cleaned[_FORCE_OVERWRITE_KEY] = bool(fd[_FORCE_OVERWRITE_KEY])
            if cleaned:
                result.character_deltas[name] = cleaned
        return result


# === 强制类型转换辅助 ===

def _coerce_score_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not k.strip():
            continue
        try:
            out[k.strip()] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


def _coerce_str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        k.strip(): v.strip()
        for k, v in value.items()
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
    }


def _merge_unique(old: list[str], new: list[str]) -> list[str]:
    """保持顺序的去重并集."""
    seen = set(old)
    out = list(old)
    for item in new:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _fmt_score(v: float) -> str:
    """整数显示为 48 而不是 48.0; 浮点保留 1 位."""
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}"
