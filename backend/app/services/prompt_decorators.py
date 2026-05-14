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


class NarratorVoiceDecorator:
    """叙述者声音装饰器 - 强制内心独白与对白符合主角年龄/时代

    解决重生类作品里"35 岁的灵魂在 18 岁躯壳里思考",
    生成的少年口吻被商战术语污染的问题。
    """

    name = "narrator_voice"

    def __init__(
        self,
        age: Optional[int] = None,
        era: Optional[str] = None,
        forbidden_vocab: Optional[list[str]] = None,
    ):
        self.age = age
        self.era = (era or "").strip()
        self.forbidden_vocab = [v.strip() for v in (forbidden_vocab or []) if v and v.strip()]

    def _is_active(self) -> bool:
        return bool(self.age or self.era or self.forbidden_vocab)

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self._is_active():
            return ctx
        lines = ["【🎭 叙述者声音 - 硬约束】"]
        if self.age:
            lines.append(f"主角当前年龄 {self.age} 岁,内心独白与对白必须符合该年龄段的认知边界。")
        if self.era:
            lines.append(f"故事时代背景:{self.era}。涉及到的物件、流行语、社会观念必须与该时代一致。")
        if self.forbidden_vocab:
            joined = "、".join(self.forbidden_vocab)
            lines.append(f"❌ 禁止主角心理活动或叙述使用以下词汇/概念:{joined}")
            lines.append("❌ 禁止用商业分析、战略评估、投资术语描述日常事件——即便主角具备超前判断,也必须落回当下年龄的语言。")
        block = "\n".join(lines)
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["narrator_voice_applied"] = True
        return ctx


class MotifCoolingDecorator:
    """已用意象冷却装饰器 - 防止主角口头禅 / 标志意象 / 场景特征词被反复磨损

    输入:
      cooling: 最近 N 章已用过的意象(建议本章避免重复)
      banned:  累计使用超阈值的意象(强制本章禁用)

    数据由 MotifExtractionHook 在生成后回写到 StoryMemory(memory_type='used_motif'),
    再由 MotifRepository 在下一章生成前读出并实例化本装饰器。
    """

    name = "motif_cooling"

    def __init__(
        self,
        cooling: Optional[list[str]] = None,
        banned: Optional[list[str]] = None,
    ):
        self.cooling = [m.strip() for m in (cooling or []) if m and m.strip()]
        self.banned = [m.strip() for m in (banned or []) if m and m.strip()]

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self.cooling and not self.banned:
            return ctx
        lines = ["【♻️ 意象去重 - 抗复读硬约束】"]
        if self.banned:
            joined = "、".join(self.banned)
            lines.append(f"🚫 本章禁止再次出现以下已被过度使用的意象/口头禅:{joined}")
        if self.cooling:
            joined = "、".join(self.cooling)
            lines.append(f"⏳ 以下意象在最近几章刚刚用过,本章请尽量回避或换种表达:{joined}")
        block = "\n".join(lines)
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["motif_cooling_applied"] = True
        return ctx


class CharacterArcDecorator:
    """角色弧线装饰器 - 把最近章节的角色状态/关系演进喂回 prompt

    数据来源: PlotAnalysis.character_states (由 SyncAnalyzeHook 在批量生成时同步写入)
    输入: arcs = [
        {"name": "周浩",
         "state": "从盲目护友升级到开始质疑主角",
         "relationships": "与林川: 信任出现裂缝; 与赵凯: 戒备加深"}
    ]
    解决症状: 配角动作模式化(总是瞪/拍/要冲) + 恋爱/对手线长期停滞
    """

    name = "character_arc"

    MAX_ARCS = 6
    BLOCK_HEADER = "【🌱 角色弧线状态 - 必须从此处接续】"

    def __init__(self, arcs: Optional[list[dict]] = None):
        self.arcs = [a for a in (arcs or []) if isinstance(a, dict) and a.get("name")]

    def _is_active(self) -> bool:
        return bool(self.arcs)

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self._is_active():
            return ctx
        lines = [self.BLOCK_HEADER,
                 "以下是各角色在最近章节里已经发生的心境/关系变化。"
                 "本章必须从这里继续推进,不要让角色退回之前的状态,也不要让他们做同一组动作。"]
        for arc in self.arcs[: self.MAX_ARCS]:
            name = (arc.get("name") or "").strip()
            state = (arc.get("state") or "").strip()
            rels = (arc.get("relationships") or "").strip()
            if not name:
                continue
            row = [f"- 【{name}】"]
            if state:
                row.append(f"心境/动作走向: {state}")
            if rels:
                row.append(f"关系演进: {rels}")
            lines.append(" / ".join(row))
        block = "\n".join(lines)
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["character_arc_applied"] = True
        return ctx


class LocationVarietyDecorator:
    """地点轮换装饰器 - 防止小说全程在 4 个场景里转

    数据来源: PlotAnalysis.scenes (由章节分析在生成后写入)
    输入: recent_locations = ["教室最后一排", "走廊", "车棚"]
    本装饰器把这些注入"近期场景"段,要求本章至少引入 1 个新场景。
    """

    name = "location_variety"

    MAX_LOCATIONS = 8

    def __init__(self, recent_locations: Optional[list[str]] = None):
        cleaned: list[str] = []
        seen: set[str] = set()
        for loc in recent_locations or []:
            if not isinstance(loc, str):
                continue
            s = loc.strip().strip('"\'「」『』《》[]()').strip()
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)
        self.recent_locations = cleaned[: self.MAX_LOCATIONS]

    def _is_active(self) -> bool:
        return bool(self.recent_locations)

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self._is_active():
            return ctx
        joined = "、".join(self.recent_locations)
        block = (
            "【📍 场景轮换 - 防止地点循环硬约束】\n"
            f"近期章节已经反复使用的场景:{joined}\n"
            "✅ 本章请至少引入 1 个未在上述列表中的新场景(可与近期场景并存)\n"
            "❌ 严禁本章自始至终只在上述场景里发生"
        )
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["location_variety_applied"] = True
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
        character_arc: Optional["CharacterArcDecorator"] = None,
        narrator_voice: Optional["NarratorVoiceDecorator"] = None,
        motif_cooling: Optional["MotifCoolingDecorator"] = None,
        location_variety: Optional["LocationVarietyDecorator"] = None,
    ) -> "PromptPipeline":
        """章节生成的标准管线(便利工厂方法)

        装饰器执行顺序(由低到高粒度叠加,后者权威性更高):
         1. WritingStyleDecorator       - 用户偏好风格
         2. StylePatternDecorator       - 作者自身写作模式(来自历史章节)
         3. CreativeContractDecorator   - 项目级硬约束
         4. VolumeBriefDecorator        - 卷级约束
         5. ChapterBriefDecorator       - 章级约束
         6. MemoryScratchpadDecorator   - 当前剧情快照
         7. CharacterArcDecorator       - 角色心境/关系演进(来自 PlotAnalysis)
         8. NarratorVoiceDecorator      - 主角声音年龄/时代硬约束
         9. MotifCoolingDecorator       - 已用意象冷却 / 禁用
        10. LocationVarietyDecorator    - 地点轮换硬约束(来自 PlotAnalysis)
        11. AntiAIFlavorDecorator       - 反 AI 味
        12. OutputFormatDecorator       - 输出指令
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
        if character_arc is not None and character_arc._is_active():
            decorators.append(character_arc)
        if narrator_voice is not None and narrator_voice._is_active():
            decorators.append(narrator_voice)
        if motif_cooling is not None and (motif_cooling.cooling or motif_cooling.banned):
            decorators.append(motif_cooling)
        if location_variety is not None and location_variety._is_active():
            decorators.append(location_variety)
        if anti_ai_enabled:
            decorators.append(AntiAIFlavorDecorator())
        decorators.append(OutputFormatDecorator())
        return cls(decorators)
