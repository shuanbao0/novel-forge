"""章节节点服务 - 借鉴 webnovel-writer 的 CBN/CPNs/CEN 三层大纲结构

数据存储:复用 outline.structure JSON 列(无需迁移),约定 "nodes" 子键
节点类型:
- CBN (Chapter Beginning Node) - 章节开局节点,1 个
- CPN (Chapter Plot Node)      - 关键剧情点,1..N 个
- CEN (Chapter Ending Node)    - 章节结尾锚,1 个

向后兼容:outline.structure 中无 "nodes" 键时,本服务返回空列表,
        ChapterContextBuilder 走原有路径,无副作用。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeType(str, Enum):
    CBN = "CBN"
    CPN = "CPN"
    CEN = "CEN"


@dataclass
class OutlineNode:
    """章节节点 - 比 outline 更细的剧情骨架单元"""
    type: NodeType
    title: str = ""
    directive: str = ""             # 节点指令(本节点必须发生什么)
    anti_patterns: list[str] = field(default_factory=list)  # 节点级反模式
    word_budget: Optional[int] = None  # 建议字数

    def to_prompt_line(self) -> str:
        parts = [f"[{self.type.value}]"]
        if self.title:
            parts.append(self.title)
        parts.append(":" + (self.directive or "(未指定指令)"))
        if self.word_budget:
            parts.append(f"(目标 ~{self.word_budget}字)")
        line = " ".join(parts)
        if self.anti_patterns:
            line += "\n  - 禁:" + "; ".join(self.anti_patterns)
        return line

    @classmethod
    def from_raw(cls, raw: Any) -> Optional["OutlineNode"]:
        if not isinstance(raw, dict):
            return None
        raw_type = str(raw.get("type", "")).upper()
        if raw_type not in NodeType.__members__:
            return None
        return cls(
            type=NodeType(raw_type),
            title=str(raw.get("title", "")).strip(),
            directive=str(raw.get("directive", "")).strip(),
            anti_patterns=[str(p).strip() for p in (raw.get("anti_patterns") or []) if str(p).strip()],
            word_budget=_safe_int(raw.get("word_budget")),
        )


def parse_outline_nodes(structure: Any) -> list[OutlineNode]:
    """从 outline.structure (str/dict) 解析节点列表

    - 兼容字符串(JSON)和已解析的 dict
    - 无 "nodes" 字段或为空 → 返回 []
    """
    if not structure:
        return []
    if isinstance(structure, str):
        try:
            structure = json.loads(structure)
        except json.JSONDecodeError:
            return []
    if not isinstance(structure, dict):
        return []

    raw_nodes = structure.get("nodes")
    if not isinstance(raw_nodes, list):
        return []

    parsed: list[OutlineNode] = []
    for raw in raw_nodes:
        node = OutlineNode.from_raw(raw)
        if node is not None:
            parsed.append(node)
    return parsed


def render_nodes_for_prompt(nodes: list[OutlineNode]) -> str:
    """把节点列表渲染成可注入大纲提示词的文本块"""
    if not nodes:
        return ""

    lines = ["【📐 章节节点结构 - 按顺序推进】"]
    for idx, node in enumerate(nodes, start=1):
        lines.append(f"{idx}. {node.to_prompt_line()}")

    lines.append(
        "\n⚠️ 节点是叙事骨架,按编号顺序推进。CBN 必须开篇出现,CEN 必须结尾承接,"
        "CPNs 是中间关键转折,顺序不可乱。每个节点的 directive 必须被覆盖。"
    )
    return "\n".join(lines)


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
