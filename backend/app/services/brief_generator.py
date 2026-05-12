"""卷/章契约 AI 生成器

设计模式:
- Builder: BriefContextBuilder 装配上下文(项目/大纲/兄弟卷/前卷 brief/项目契约)
- Template Method: BaseBriefGenerator.generate() 固定"构 prompt → 调 AI → 解析 → 校验"流程
- Strategy: VolumeBriefGenerator (后续可加 ChapterBriefGenerator) 仅替换 prompt + schema

不依赖 SSE/HTTP, 纯领域服务, 便于被 API 层或后台任务复用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.outline import Outline
from app.models.project import Project
from app.services.ai_service import AIService
from app.services.creative_contract import CreativeContract, VolumeBrief
from app.services.json_helper import parse_json

logger = get_logger(__name__)


@dataclass
class BriefContext:
    """生成 brief 所需的全部上下文"""
    project: Project
    target_outline: Outline
    sibling_outlines: list[Outline]
    project_contract: CreativeContract
    prev_brief: Optional[VolumeBrief]

    @property
    def total_volumes(self) -> int:
        return len(self.sibling_outlines)

    @property
    def position(self) -> str:
        """本卷在故事弧线的位置(开端/发展/高潮/收束)"""
        idx = self.target_outline.order_index
        total = self.total_volumes or 1
        ratio = idx / total
        if ratio <= 0.25:
            return "开端(铺设角色与冲突)"
        if ratio <= 0.6:
            return "发展(矛盾升级与世界扩张)"
        if ratio <= 0.85:
            return "高潮(核心冲突爆发与转折)"
        return "收束(承诺兑现与余韵)"


class BriefContextBuilder:
    """从 DB 装配 BriefContext"""

    @staticmethod
    async def build(outline_id: str, db: AsyncSession) -> BriefContext:
        outline = await db.get(Outline, outline_id)
        if not outline:
            raise ValueError(f"大纲不存在: {outline_id}")

        project = await db.get(Project, outline.project_id)
        if not project:
            raise ValueError(f"项目不存在: {outline.project_id}")

        result = await db.execute(
            select(Outline)
            .where(Outline.project_id == outline.project_id)
            .order_by(Outline.order_index)
        )
        siblings = list(result.scalars().all())

        prev_brief: Optional[VolumeBrief] = None
        for sib in siblings:
            if sib.order_index < outline.order_index and sib.creative_brief:
                prev_brief = VolumeBrief.from_raw(sib.creative_brief)

        return BriefContext(
            project=project,
            target_outline=outline,
            sibling_outlines=siblings,
            project_contract=CreativeContract.from_raw(project.creative_contract),
            prev_brief=prev_brief,
        )


class BriefGenerationError(Exception):
    """brief 生成失败(解析/校验)"""


class BaseBriefGenerator(ABC):
    """Template Method - 固定生成流程, 子类替换 prompt / 解析 / 校验"""

    temperature: float = 0.7
    max_tokens: int = 1500

    def __init__(self, ai_service: AIService):
        self.ai = ai_service

    async def generate(
        self,
        ctx: BriefContext,
        user_hint: Optional[str] = None,
        max_retries: int = 1,
    ) -> dict:
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            corrective = "" if attempt == 0 else (
                f"\n\n[上次输出无法解析为合法 JSON, 错误: {last_err}. "
                f"请严格按要求的 JSON 结构重新输出, 不要包裹 markdown 代码块。]"
            )
            prompt = self.build_prompt(ctx, user_hint) + corrective

            response = await self.ai.generate_text(
                prompt=prompt,
                system_prompt=self.system_prompt(),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                auto_mcp=False,
            )
            raw = (response.get("content") or "").strip()
            if not raw:
                last_err = BriefGenerationError("AI 返回为空")
                continue

            try:
                data = parse_json(raw)
                return self.validate(data)
            except Exception as e:
                last_err = e
                logger.warning(
                    f"brief 生成第 {attempt + 1} 次解析/校验失败: {e}"
                )

        raise BriefGenerationError(f"brief 生成失败: {last_err}")

    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def build_prompt(self, ctx: BriefContext, user_hint: Optional[str]) -> str: ...

    @abstractmethod
    def validate(self, raw: object) -> dict: ...


class VolumeBriefGenerator(BaseBriefGenerator):
    """卷级契约生成器 - 输出 {volume_goal, pacing, anti_patterns[], required_tropes[]}"""

    PACING_OPTIONS = {"fast", "medium", "slow"}

    def system_prompt(self) -> str:
        return (
            "你是一名资深网文编辑, 擅长把卷级目标拆解成可执行的写作约束。"
            "你的产出会作为 AI 章节生成的硬约束, 因此必须:"
            "(1) 具体到能裁定一句话是否违反; "
            "(2) 不与项目级契约重复, 只补充本卷专属约束; "
            "(3) 与前一卷的 brief 保持语气与底层逻辑连贯, 但禁忌/桥段不能照抄。"
            "始终用纯 JSON 输出, 不要 markdown 代码块, 不要解释。"
        )

    def build_prompt(self, ctx: BriefContext, user_hint: Optional[str]) -> str:
        project = ctx.project
        outline = ctx.target_outline

        sibling_lines = []
        for sib in ctx.sibling_outlines:
            marker = "👉" if sib.id == outline.id else "  "
            preview = (sib.content or "").strip().replace("\n", " ")[:120]
            sibling_lines.append(
                f"{marker} 第{sib.order_index}卷《{sib.title}》: {preview}"
            )
        sibling_block = "\n".join(sibling_lines) or "(暂无其他卷)"

        project_contract_block = ctx.project_contract.to_prompt_block() or "(项目未设置全局契约)"
        prev_block = ctx.prev_brief.to_prompt_block() if ctx.prev_brief else "(本卷是第一卷)"

        hint_block = f"\n## 用户额外提示\n{user_hint.strip()}\n" if user_hint and user_hint.strip() else ""

        return f"""请为下列卷生成"卷级契约"。

# 项目背景
- 标题: {project.title}
- 类型: {project.genre or '未指定'}
- 主题: {project.theme or '未指定'}
- 叙事视角: {project.narrative_perspective or '未指定'}
- 世界氛围: {project.world_atmosphere or '未指定'}

# 项目级契约(已声明的全局硬约束, 本卷不要重复)
{project_contract_block}

# 上一卷的卷契约(保持连贯但不可照抄)
{prev_block}

# 全卷概览(👉 标记本卷, 你正在为它生成 brief)
{sibling_block}

# 本卷信息
- 序号: 第 {outline.order_index} 卷 / 共 {ctx.total_volumes} 卷
- 弧线位置: {ctx.position}
- 标题: {outline.title}
- 内容: {(outline.content or '').strip()}
{hint_block}
# 输出要求
仅输出下列 JSON, 字段不可缺失:
{{
  "volume_goal": "<本卷叙事目标. 必须包含 1 个具体转折点 + 1 个情感锚点, 不超过 180 字>",
  "pacing": "<fast | medium | slow, 三选一>",
  "anti_patterns": ["<本卷专属反模式, 3-6 条, 不与项目级反模式重复>"],
  "required_tropes": ["<本卷必须出现的桥段, 3-6 条, 不与上一卷 required_tropes 重复>"]
}}

# 质量自检(输出前请自查)
- volume_goal 是否能让编辑判断"本卷写完没有"?
- anti_patterns 每一条是否能裁定一句正文是否违反?
- required_tropes 是否服务于"弧线位置"所要求的剧情功能?
"""

    def validate(self, raw: object) -> dict:
        if not isinstance(raw, dict):
            raise BriefGenerationError(f"期望 dict, 实际为 {type(raw).__name__}")

        goal = str(raw.get("volume_goal", "") or "").strip()
        pacing = str(raw.get("pacing", "") or "").strip().lower()
        anti = _normalize_list(raw.get("anti_patterns"))
        tropes = _normalize_list(raw.get("required_tropes"))

        if not goal:
            raise BriefGenerationError("volume_goal 不能为空")
        if len(goal) > 400:
            goal = goal[:400]
        if pacing and pacing not in self.PACING_OPTIONS:
            pacing = ""
        anti = anti[:8]
        tropes = tropes[:8]

        return {
            "volume_goal": goal,
            "pacing": pacing,
            "anti_patterns": anti,
            "required_tropes": tropes,
        }


def _normalize_list(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]
