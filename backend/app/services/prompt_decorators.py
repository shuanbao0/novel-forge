"""提示词装饰器管线 - 用 Decorator + Pipeline 模式串联 prompt 后处理

设计目标:
- 把 system_prompt / user_prompt 的修饰逻辑从 API 层抽出
- 每条规则一个独立 Decorator,可单独测试、可按用户配置启停
- 顺序敏感:写作风格 -> 反 AI 味 -> 输出格式

借鉴: webnovel-writer 的 context-agent.md 反 AI 对策
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from app.services.creative_contract import (
    ChapterBrief,
    CreativeContract,
    VolumeBrief,
)


@dataclass
class PromptContext:
    """提示词上下文 - 在 Decorator 间流转的可变状态容器"""
    user_prompt: str
    system_prompt: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class PromptDecorator(Protocol):
    """提示词装饰器协议"""
    name: str

    def apply(self, ctx: PromptContext) -> PromptContext:
        ...


class StylePatternDecorator:
    """风格模式装饰器 - 把作者从既往章节中抽取的写作特征注入

    与 MemoryScratchpad 平行:scratchpad 关心"剧情状态",pattern 关心"语言风格"。
    位置:用户风格之后、契约之前(用户主动选风格优先级最高,作者风格作为辅助)。
    """

    name = "style_pattern"

    def __init__(self, pattern_text: Optional[str]):
        self.text = (pattern_text or "").strip()

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self.text:
            return ctx
        ctx.system_prompt = (
            self.text if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{self.text}"
        )
        ctx.metadata["style_pattern_applied"] = True
        return ctx


class MemoryScratchpadDecorator:
    """记忆便签装饰器 - 把最近剧情快照注入 system_prompt

    与契约装饰器并列;在所有契约之后追加,体现"约束 + 当前状态"两层注入。
    """

    name = "memory_scratchpad"

    def __init__(self, scratchpad_text: Optional[str]):
        self.text = (scratchpad_text or "").strip()

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self.text:
            return ctx
        ctx.system_prompt = (
            self.text if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{self.text}"
        )
        ctx.metadata["scratchpad_applied"] = True
        return ctx


class CreativeContractDecorator:
    """创作契约装饰器 - 把项目级硬约束注入 system_prompt

    位置优先于反 AI 味,但低于写作风格。空契约自动跳过。
    """

    name = "creative_contract"

    def __init__(self, contract: Optional[CreativeContract]):
        self.contract = contract or CreativeContract()

    def apply(self, ctx: PromptContext) -> PromptContext:
        block = self.contract.to_prompt_block()
        if not block:
            return ctx
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["contract_applied"] = True
        return ctx


class VolumeBriefDecorator:
    """卷级契约装饰器 - 优先级介于项目契约和章节契约之间"""

    name = "volume_brief"

    def __init__(self, brief: Optional[VolumeBrief]):
        self.brief = brief or VolumeBrief()

    def apply(self, ctx: PromptContext) -> PromptContext:
        block = self.brief.to_prompt_block()
        if not block:
            return ctx
        ctx.system_prompt = block if not ctx.system_prompt else f"{ctx.system_prompt}\n\n{block}"
        ctx.metadata["volume_brief_applied"] = True
        return ctx


class ChapterBriefDecorator:
    """章级契约装饰器 - 最高优先级的局部约束"""

    name = "chapter_brief"

    def __init__(self, brief: Optional[ChapterBrief]):
        self.brief = brief or ChapterBrief()

    def apply(self, ctx: PromptContext) -> PromptContext:
        block = self.brief.to_prompt_block()
        if not block:
            return ctx
        ctx.system_prompt = block if not ctx.system_prompt else f"{ctx.system_prompt}\n\n{block}"
        ctx.metadata["chapter_brief_applied"] = True
        return ctx


class WritingStyleDecorator:
    """将用户选定的写作风格注入到 system_prompt(最高优先级)"""

    name = "writing_style"

    def __init__(self, style_content: str):
        self.style_content = (style_content or "").strip()

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self.style_content:
            return ctx
        injected = (
            "【🎨 写作风格要求 - 最高优先级】\n\n"
            f"{self.style_content}\n\n"
            "⚠️ 请严格遵循上述写作风格要求进行创作,这是最重要的指令!\n"
            "确保在整个章节创作过程中始终保持风格的一致性。"
        )
        ctx.system_prompt = (
            injected if not ctx.system_prompt
            else f"{injected}\n\n---\n\n{ctx.system_prompt}"
        )
        ctx.metadata["style_applied"] = True
        return ctx


class AntiAIFlavorDecorator:
    """反 AI 味装饰器 - 注入 7 条反模板化创作规则

    借鉴自 webnovel-writer/agents/context-agent.md (反 AI 对策)
    针对中文网文生成中常见的 AI 通病
    """

    name = "anti_ai_flavor"

    # 7 条核心规则 - 可按需配置启用子集
    DEFAULT_RULES: tuple[str, ...] = (
        "禁用模板化副词:缓缓、淡淡、微微、默默、轻轻、慢慢——用具体动作或环境暗示替代",
        "禁用情绪标签直述:不要写「他很愤怒」「她感到悲伤」,用动作、生理反应、对话节奏表现情绪",
        "禁用万能形容词:「美丽的」「神秘的」「强大的」要落到具体感官细节(她的左手有三道旧疤)",
        "禁用结尾陈述句/抒情总结:章节结尾留悬念、动作未完或对话被打断,不要总结陈述",
        "禁用 AI 套路开场:「夜幕降临」「阳光洒在」「某年某月某日」等模板化开头",
        "对话要有个性差异:不同角色用词、语速、口头禅不同,避免所有人都「文绉绉」",
        "动作要有物理细节:谁、用哪只手、什么角度、对方什么反应——而非抽象的「他攻击她」",
    )

    def __init__(self, rules: Optional[tuple[str, ...]] = None, enabled: bool = True):
        self.rules = rules or self.DEFAULT_RULES
        self.enabled = enabled

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self.enabled or not self.rules:
            return ctx
        block = "【⚠️ 写作禁区 - 反 AI 味强约束】\n" + "\n".join(
            f"❌ {rule}" for rule in self.rules
        )
        # 追加到 system_prompt(若无则建一个),保证比 user_prompt 优先级更高
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["anti_ai_applied"] = True
        return ctx


class OutputFormatDecorator:
    """输出格式装饰器 - 章节生成场景的统一收尾指令"""

    name = "output_format"

    def __init__(
        self,
        instruction: str = "请直接输出章节正文内容,不要包含章节标题和其他说明文字。",
    ):
        self.instruction = instruction

    def apply(self, ctx: PromptContext) -> PromptContext:
        ctx.user_prompt = f"{ctx.user_prompt}\n\n{self.instruction}"
        return ctx


class PromptPipeline:
    """提示词处理管线

    用法:
        pipeline = PromptPipeline([
            WritingStyleDecorator(style_content),
            AntiAIFlavorDecorator(),
            OutputFormatDecorator(),
        ])
        ctx = pipeline.run(PromptContext(user_prompt=base_prompt))
        # ctx.user_prompt / ctx.system_prompt 即为最终值
    """

    def __init__(self, decorators: list[PromptDecorator]):
        self.decorators = decorators

    def run(self, ctx: PromptContext) -> PromptContext:
        for decorator in self.decorators:
            ctx = decorator.apply(ctx)
        return ctx

    @classmethod
    def for_chapter_generation(
        cls,
        style_content: Optional[str] = None,
        anti_ai_enabled: bool = True,
        contract: Optional[CreativeContract] = None,
        volume_brief: Optional[VolumeBrief] = None,
        chapter_brief: Optional[ChapterBrief] = None,
        scratchpad_text: Optional[str] = None,
        style_pattern_text: Optional[str] = None,
    ) -> "PromptPipeline":
        """章节生成的标准管线(便利工厂方法)

        装饰器执行顺序(由低到高粒度叠加,后者权威性更高):
        1. WritingStyleDecorator     - 用户偏好风格
        2. StylePatternDecorator     - 作者自身写作模式(来自历史章节)
        3. CreativeContractDecorator - 项目级硬约束
        4. VolumeBriefDecorator      - 卷级约束
        5. ChapterBriefDecorator     - 章级约束
        6. MemoryScratchpadDecorator - 当前剧情快照
        7. AntiAIFlavorDecorator     - 反 AI 味
        8. OutputFormatDecorator     - 输出指令
        """
        decorators: list[PromptDecorator] = []
        if style_content:
            decorators.append(WritingStyleDecorator(style_content))
        if style_pattern_text:
            decorators.append(StylePatternDecorator(style_pattern_text))
        if contract and not contract.is_empty():
            decorators.append(CreativeContractDecorator(contract))
        if volume_brief and not volume_brief.is_empty():
            decorators.append(VolumeBriefDecorator(volume_brief))
        if chapter_brief and not chapter_brief.is_empty():
            decorators.append(ChapterBriefDecorator(chapter_brief))
        if scratchpad_text:
            decorators.append(MemoryScratchpadDecorator(scratchpad_text))
        if anti_ai_enabled:
            decorators.append(AntiAIFlavorDecorator())
        decorators.append(OutputFormatDecorator())
        return cls(decorators)
