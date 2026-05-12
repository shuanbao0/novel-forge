"""结构化润色指南 - 借鉴 webnovel-writer polish-guides 系统

把"如何写好"拆成 6 个独立维度,每个维度一个 Guide,含规则 + 正反例。
Polish API 允许选择一组 Guide,把它们的规则拼成专门的润色 prompt。

设计:
- Guide 是只读静态数据(无需 DB)
- 用 dataclass(frozen=True) 防止意外修改
- 按 id 索引,API 接受 list[guide_id]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class PolishGuide:
    id: str
    name: str
    focus: str                                  # 一句话核心
    rules: tuple[str, ...] = ()                # 具体改写规则
    examples_good: tuple[str, ...] = ()        # 好例子(应保留/模仿)
    examples_bad: tuple[str, ...] = ()         # 坏例子(应消除)

    def to_prompt_block(self) -> str:
        parts = [f"## 维度:{self.name}", f"焦点:{self.focus}"]
        if self.rules:
            parts.append("规则:")
            parts.extend(f"  - {r}" for r in self.rules)
        if self.examples_bad:
            parts.append("反例(应改掉):")
            parts.extend(f"  ✗ {e}" for e in self.examples_bad)
        if self.examples_good:
            parts.append("正例(应模仿):")
            parts.extend(f"  ✓ {e}" for e in self.examples_good)
        return "\n".join(parts)


_GUIDES: dict[str, PolishGuide] = {
    "scene_description": PolishGuide(
        id="scene_description",
        name="场景描写",
        focus="用感官细节代替形容词标签",
        rules=(
            "禁用'美丽的/壮观的/恢宏的'等抽象形容词,换具体感官细节",
            "至少包含 2 种感官(视/听/嗅/触/味)",
            "镜头要有焦点:远景 → 中景 → 特写,而非平铺直叙",
            "环境应间接反映人物处境/情绪,而非中立背景",
        ),
        examples_bad=(
            "那是一个美丽的早晨,阳光洒在大地上。",
            "宫殿无比恢宏,让人惊叹。",
        ),
        examples_good=(
            "晨雾还没散,他靴底踩过的石板留下两个湿黑印子。远处有人在敲铜钟。",
            "梁柱比三人合抱还粗,他抬头看了三次才看见顶。",
        ),
    ),
    "emotion_rendering": PolishGuide(
        id="emotion_rendering",
        name="情感渲染",
        focus="用动作/生理反应/失态代替情绪标签",
        rules=(
            "禁用'他很愤怒/她很悲伤/心如刀绞'等直陈,换生理 + 动作",
            "情绪应有'打断点'——一个外部细节中断角色,体现情绪压不住",
            "对话节奏暗示情绪:愤怒时短句,委屈时长句,慌乱时碎语",
            "用沉默/动作错位/反复看同一处来表达克制",
        ),
        examples_bad=(
            "他非常愤怒,简直要爆炸了。",
            "她心如刀绞,泪如雨下。",
        ),
        examples_good=(
            "他把茶杯放回桌上,杯底磕到了第二次才放稳。",
            "她笑了一下,然后转身去关窗,关了两遍。",
        ),
    ),
    "dialogue_rhythm": PolishGuide(
        id="dialogue_rhythm",
        name="对话节奏",
        focus="对话有差异化、有信息差、被动作打断",
        rules=(
            "不同角色用词/语速/口头禅应有明显差异,避免所有人都'文绉绉'",
            "对话中应有信息差:角色 A 知道 X 而 B 不知道,张力自然产生",
            "对话被动作/环境打断 1-2 次,而非连续长篇",
            "禁用'……他说道'这种纯标签,换成'他没看她,继续切菜'之类的动作指代",
        ),
        examples_bad=(
            '"你为什么要这么做?"他问道。"因为我不得不。"她说道。"我不理解。"他说道。',
        ),
        examples_good=(
            '"你为什么要这么做。" 他没有抬头,刀刃停在萝卜上。\n她想说话,但门外传来脚步声。她又把话咽了回去。',
        ),
    ),
    "action_choreography": PolishGuide(
        id="action_choreography",
        name="动作编排",
        focus="动作要有物理细节、节奏感、空间方位",
        rules=(
            "禁用抽象'他攻击她',明确:谁的左手、哪个角度、对方什么反应",
            "动作有节奏分组:发力 → 接触 → 反应,不能一句话过完",
            "环境元素参与动作:武器碰到桌角、绊到台阶、踢翻了水盆",
            "重要动作配一个慢镜头细节:'剑尖颤抖了一下'",
        ),
        examples_bad=(
            "他一拳打过去,把对方打飞了。",
        ),
        examples_good=(
            "他左肩沉了沉,拳头从腰下斜着出去。对方堪堪侧身,衣角被风带得贴在墙上。",
        ),
    ),
    "pacing_control": PolishGuide(
        id="pacing_control",
        name="节奏控制",
        focus="张弛有度、关键转折要铺垫、不重要的事一笔带过",
        rules=(
            "关键转折前要有 50-200 字的环境/心理铺垫,不能直接发生",
            "次要场景过渡可一句话:'三天之后,他回到了山门外。'",
            "高潮段落要拉长(放大慢镜头),平淡段落要压缩",
            "段落长度交替:长 → 短 → 短 → 长,避免连续长段催眠",
        ),
        examples_bad=(
            "他走进去,看见敌人,然后杀了他,出来吃饭。",
        ),
        examples_good=(
            "他在门外停了一下。\n屋里没有声音,只有檐角滴水。三滴。四滴。第五滴落下来时,他推开了门。",
        ),
    ),
    "sensory_detail": PolishGuide(
        id="sensory_detail",
        name="感官细节",
        focus="用低饱和度的具体细节制造真实感",
        rules=(
            "每个重要场景至少出现 1 个不直接服务情节的环境细节",
            "细节要'低饱和度':一只迟到的麻雀、一个洗得发白的衣领,而非奇观",
            "气味/温度是最便宜也最有效的真实感来源",
            "时间要具体:'快到午时'而非'白天','灯油剩了三分'而非'晚上'",
        ),
        examples_bad=(
            "屋子里很暗,只有一盏灯。",
        ),
        examples_good=(
            "灯油剩了三分,芯子结了个黑头,光只够照到桌沿。",
        ),
    ),
}


def get_guide(guide_id: str) -> Optional[PolishGuide]:
    return _GUIDES.get(guide_id)


def list_guides() -> list[PolishGuide]:
    return list(_GUIDES.values())


def render_guides_prompt(guide_ids: list[str]) -> str:
    """选定多个 guide,渲染成可注入润色 prompt 的复合指南文本

    未知 id 静默跳过;空列表返回空串(调用方按"无 guides"路径处理)。
    """
    guides = [g for gid in guide_ids if (g := _GUIDES.get(gid))]
    if not guides:
        return ""
    blocks = ["【🪶 结构化润色指南】", "按以下维度逐一改写,每个维度都要应用其规则。"]
    for g in guides:
        blocks.append("")
        blocks.append(g.to_prompt_block())
    blocks.append("\n【输出要求】只输出润色后的正文,不要解释、不要说明做了什么。")
    return "\n".join(blocks)
