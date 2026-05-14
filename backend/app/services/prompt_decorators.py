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


class PacingMilestoneDecorator:
    """卷级节奏里程碑装饰器 - 防止整本书在前几章原地踏步

    数据来源: VolumeBrief.pacing_milestones (用户/规划阶段配置)
              形式 [{"by_chapter": int, "milestone": str}, ...]
    解决症状: 5 章 7 万字只推进一天剧情,主线迟迟不动。

    分类逻辑:
      - overdue:  by_chapter < current,但本卷至今未完成 → 写"已逾期警告"
      - imminent: current <= by_chapter <= current + lookahead → 写"即将到期提醒"

    注意: 本装饰器只做"提醒推进",并不能判断里程碑是否真的已达成
    (那需要 PlotAnalyzer 输出 milestone_progress, 留待 Phase 2)。
    本期通过 by_chapter 与 current_chapter 的比较给出"应该推进"的硬约束。
    """

    name = "pacing_milestone"
    BLOCK_HEADER = "【🎯 本卷节奏里程碑 - 推进硬约束】"
    DEFAULT_LOOKAHEAD = 2

    def __init__(
        self,
        milestones: Optional[list[dict]] = None,
        current_chapter: int = 0,
        lookahead: int = DEFAULT_LOOKAHEAD,
    ):
        self.current = current_chapter
        cleaned: list[dict] = []
        for m in milestones or []:
            if not isinstance(m, dict):
                continue
            by = m.get("by_chapter")
            text = (m.get("milestone") or "").strip()
            if not text or not isinstance(by, int) or by <= 0:
                continue
            cleaned.append({"by_chapter": by, "milestone": text})
        cleaned.sort(key=lambda x: x["by_chapter"])
        self.overdue = [m for m in cleaned if m["by_chapter"] < current_chapter]
        self.imminent = [
            m for m in cleaned
            if current_chapter <= m["by_chapter"] <= current_chapter + lookahead
        ]

    def _is_active(self) -> bool:
        return bool(self.overdue or self.imminent)

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self._is_active():
            return ctx
        lines = [self.BLOCK_HEADER]
        if self.overdue:
            lines.append(
                "🚨 以下里程碑已逾期(原计划在更早章节完成),本章必须立刻推进或当章完结:"
            )
            for m in self.overdue:
                lines.append(f"  - 原定第 {m['by_chapter']} 章前: {m['milestone']}")
        if self.imminent:
            lines.append(
                "⏳ 以下里程碑临近,本章及随后 1-2 章需为其铺设并完成:"
            )
            for m in self.imminent:
                gap = m["by_chapter"] - self.current
                tag = "本章" if gap <= 0 else f"第 {m['by_chapter']} 章前(剩 {gap} 章)"
                lines.append(f"  - {tag}: {m['milestone']}")
        lines.append("❌ 严禁本章继续在原节拍内打转而不向上述里程碑推进")
        block = "\n".join(lines)
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["pacing_milestone_applied"] = True
        return ctx


class StoryTimelineDecorator:
    """故事时间锚装饰器 - 防止前后章故事内时间漂移

    数据来源: 本章 + 上一章 expansion_plan.story_time_anchor / story_time_advance
    解决症状: 实测第 1 章定锚 5/7,第 5 章漂到"五月底",中间只过了一天剧情。

    任意一端缺数据时仅渲染另一端,两端皆缺则跳过。
    """

    name = "story_timeline"
    BLOCK_HEADER = "【⏰ 故事时间锚 - 必须严格遵守】"

    def __init__(
        self,
        prev_anchor: Optional[str] = None,
        current_anchor: Optional[str] = None,
        advance: Optional[str] = None,
    ):
        self.prev = (prev_anchor or "").strip()
        self.cur = (current_anchor or "").strip()
        self.advance = (advance or "").strip()

    def _is_active(self) -> bool:
        return bool(self.prev or self.cur)

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self._is_active():
            return ctx
        lines = [self.BLOCK_HEADER]
        if self.prev:
            lines.append(f"上一章故事内时间: {self.prev}")
        if self.cur:
            lines.append(f"本章应发生于:     {self.cur}")
        if self.advance:
            lines.append(f"本章相对上章推进: {self.advance}")
        lines.append("❌ 严禁本章故事时间向后跳跃超过上述推进幅度")
        lines.append("❌ 严禁出现与上述时间锚矛盾的季节/天气/时段描述")
        lines.append("✅ 章节内的具体时间表达(几点/上午/傍晚)必须与时间锚自洽")
        block = "\n".join(lines)
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["story_timeline_applied"] = True
        return ctx


class PlotBeatCoolingDecorator:
    """已写桥段冷却装饰器 - 防止"老师训话/对手挑衅/主角内心独白"等事件反复重演

    数据来源: PlotAnalysis.plot_points (由 PlotAnalyzer 在生成后写入,
    每条含 content/type/impact/importance)
    输入: recent_beats = [
        {"chapter_number": 2, "content": "王启明当众点名训话", "type": "conflict"},
        {"chapter_number": 2, "content": "赵凯阴阳怪气挑衅",  "type": "conflict"},
        ...
    ]

    解决症状: 同类事件(训话/嘲讽/独白)在 2/4/5 章原样重演 - LocationVariety
    只防"地点循环",MotifCooling 只防"短意象词"复读,中间这层"事件桥段"
    此前没有任何反馈环。本装饰器把最近若干章的高重要度情节点列给 LLM,
    强制要求本章推到全新事件类型。
    """

    name = "plot_beat_cooling"

    MAX_BEATS = 12
    BLOCK_HEADER = "【🔁 已写桥段冷却 - 反复演硬约束】"

    def __init__(self, recent_beats: Optional[list[dict]] = None):
        cleaned: list[dict] = []
        for b in recent_beats or []:
            if not isinstance(b, dict):
                continue
            content = (b.get("content") or "").strip()
            if not content:
                continue
            cleaned.append({
                "chapter_number": b.get("chapter_number"),
                "content": content[:80],
                "type": (b.get("type") or "").strip(),
            })
        self.recent_beats = cleaned[: self.MAX_BEATS]

    def _is_active(self) -> bool:
        return bool(self.recent_beats)

    def apply(self, ctx: PromptContext) -> PromptContext:
        if not self._is_active():
            return ctx
        lines = [
            self.BLOCK_HEADER,
            "下列情节点已在最近章节真实写过,本章必须推动到全新事件,"
            "禁止用相同的事件类型(如反复\"老师训话/对手挑衅/主角内心回顾过往\")再演一次。",
        ]
        for b in self.recent_beats:
            ch = b.get("chapter_number")
            tag = f"第{ch}章" if ch else "近章"
            kind = f"[{b['type']}]" if b["type"] else ""
            lines.append(f"- {tag}{kind} {b['content']}")
        block = "\n".join(lines)
        ctx.system_prompt = (
            block if not ctx.system_prompt
            else f"{ctx.system_prompt}\n\n{block}"
        )
        ctx.metadata["plot_beat_cooling_applied"] = True
        return ctx


class AntiAIFlavorDecorator:
    """反 AI 味装饰器 - 注入两组反模板化创作规则

    规则按粒度分两组,默认全启用,可分别覆盖:
      - SENTENCE_LEVEL_RULES: 句法层(副词/形容词/陈述句),原 7 条
      - STRUCTURAL_RULES:     段落/章级结构层(回溯段密度/内心戏连续/段首套路句),
                              针对重生文/穿越文/回忆文常见的"段落级 AI 套路"

    借鉴自 webnovel-writer/agents/context-agent.md (反 AI 对策)
    """

    name = "anti_ai_flavor"

    # 句法层 - 句子内部的用词/句式
    SENTENCE_LEVEL_RULES: tuple[str, ...] = (
        "禁用模板化副词:缓缓、淡淡、微微、默默、轻轻、慢慢——用具体动作或环境暗示替代",
        "禁用情绪标签直述:不要写「他很愤怒」「她感到悲伤」,用动作、生理反应、对话节奏表现情绪",
        "禁用万能形容词:「美丽的」「神秘的」「强大的」要落到具体感官细节(她的左手有三道旧疤)",
        "禁用结尾陈述句/抒情总结:章节结尾留悬念、动作未完或对话被打断,不要总结陈述",
        "禁用 AI 套路开场:「夜幕降临」「阳光洒在」「某年某月某日」等模板化开头",
        "对话要有个性差异:不同角色用词、语速、口头禅不同,避免所有人都「文绉绉」",
        "动作要有物理细节:谁、用哪只手、什么角度、对方什么反应——而非抽象的「他攻击她」",
    )

    # 结构层 - 段落与段落之间的节奏/比例
    STRUCTURAL_RULES: tuple[str, ...] = (
        "回溯类段落(以「前世」「记得」「想起」「那年」「当年」开头)全章合计最多 3 处,严禁连续 2 段都是回溯",
        "主角内心独白段落不得连续超过 3 段,必须用对话/外部动作/场景切换打断后再回到内心",
        "段首套路句「他想到」「他想起」「他记得」「他知道」全章合计最多 2 次",
    )

    def __init__(
        self,
        sentence_rules: Optional[tuple[str, ...]] = None,
        structural_rules: Optional[tuple[str, ...]] = None,
        enabled: bool = True,
    ):
        sl = self.SENTENCE_LEVEL_RULES if sentence_rules is None else sentence_rules
        st = self.STRUCTURAL_RULES if structural_rules is None else structural_rules
        self.rules: tuple[str, ...] = tuple(sl) + tuple(st)
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
        plot_beat_cooling: Optional["PlotBeatCoolingDecorator"] = None,
        story_timeline: Optional["StoryTimelineDecorator"] = None,
        pacing_milestone: Optional["PacingMilestoneDecorator"] = None,
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
        11. PlotBeatCoolingDecorator    - 已写桥段冷却(来自 PlotAnalysis.plot_points)
        12. StoryTimelineDecorator      - 故事内时间锚(来自 expansion_plan.story_time_*)
        13. PacingMilestoneDecorator    - 卷级节奏里程碑(来自 VolumeBrief.pacing_milestones)
        14. AntiAIFlavorDecorator       - 反 AI 味(句法 + 结构两组规则)
        15. OutputFormatDecorator       - 输出指令
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
        if plot_beat_cooling is not None and plot_beat_cooling._is_active():
            decorators.append(plot_beat_cooling)
        if story_timeline is not None and story_timeline._is_active():
            decorators.append(story_timeline)
        if pacing_milestone is not None and pacing_milestone._is_active():
            decorators.append(pacing_milestone)
        if anti_ai_enabled:
            decorators.append(AntiAIFlavorDecorator())
        decorators.append(OutputFormatDecorator())
        return cls(decorators)
