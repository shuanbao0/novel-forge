"""实体消歧 - 借鉴 webnovel-writer data-agent 的 disambiguation_result

扫描章节正文,找出疑似角色名但不在 Character 表中的字符串,给出处置建议:
- new_entity: 高置信度新角色,建议入库
- alias: 中等置信度,可能是已有角色的别名/称呼
- noise: 低置信度,可能是错误识别

实现策略(零 LLM 成本):
1. 正则提取候选(2-4 字中文连续字符,首字为常用姓氏 OR 紧邻"是/叫/名/唤")
2. 与现有角色名做模糊匹配(子串/编辑距离)
3. 出现频次 >= 2 时升级置信度
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


# 简化版常见中文姓氏(覆盖率约 90%)
_COMMON_SURNAMES = set(
    "李王张刘陈杨黄赵吴周徐孙马朱胡郭何林高罗郑梁谢宋唐许韩冯邓曹彭"
    "曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖"
    "贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱"
)


@dataclass
class EntityCandidate:
    surface: str           # 文本中出现的字面形式
    confidence: float      # 0.0 - 1.0
    suggestion: str        # new_entity / alias / noise
    occurrences: int
    similar_to: str = ""   # 最相似的已有角色(若有)


def disambiguate(
    chapter_content: str,
    known_characters: Iterable[str],
) -> list[EntityCandidate]:
    """主入口 - 返回排序后的候选列表(置信度降序)"""
    if not chapter_content:
        return []
    known = {name.strip() for name in known_characters if name and name.strip()}

    # 1. 候选提取
    raw_candidates = _extract_candidates(chapter_content)
    # 过滤掉直接命中已有角色的
    raw_candidates = [c for c in raw_candidates if c not in known]
    if not raw_candidates:
        return []

    # 2. 频次统计
    counter = Counter(raw_candidates)

    # 3. 对每个候选评分
    results: list[EntityCandidate] = []
    for name, count in counter.items():
        similar = _find_similar(name, known)
        confidence, suggestion = _score(name, count, similar)
        results.append(EntityCandidate(
            surface=name,
            confidence=round(confidence, 2),
            suggestion=suggestion,
            occurrences=count,
            similar_to=similar,
        ))

    results.sort(key=lambda c: (-c.confidence, -c.occurrences))
    return results


# === 内部 ===

# 候选名模式:中文姓氏 + 1-3 个汉字  (优先匹配 3-4 字全名)
_NAME_PATTERN = re.compile(r"[\u4e00-\u9fa5]{2,4}")
_SURFACE_BLOCKLIST = {
    "什么", "怎么", "这样", "那样", "可是", "但是", "如果", "因为", "所以", "突然",
    "已经", "终于", "马上", "立刻", "原来", "现在", "刚才", "听说", "好像", "似乎",
    "感觉", "觉得", "看见", "听见", "知道", "明白", "决定", "希望", "可能", "也许",
}


def _extract_candidates(text: str) -> list[str]:
    """从正文中抽取疑似人名

    策略:
    1. 先按非汉字字符切片,避免跨标点/动词把"李寒和"识别为一个名字
    2. 在每个汉字片段内,从姓氏开始尝试 2/3/4 字窗口,取最长合理窗口
    """
    candidates: list[str] = []

    # 1. 按非汉字字符切片
    segments = re.split(r"[^\u4e00-\u9fa5]+", text)

    for seg in segments:
        if len(seg) < 2:
            continue
        # 在片段内逐字符尝试匹配姓氏
        # 策略:优先取 3 字名(中国最常见),其次 2 字名,4 字仅在前 3 字明显是单姓+常见名时考虑
        i = 0
        while i < len(seg) - 1:
            if seg[i] not in _COMMON_SURNAMES:
                i += 1
                continue
            # 找出最长合理名字
            best_name = None
            best_end = i + 2
            for length in (3, 2):  # 优先 3 字,再 2 字
                end = i + length
                if end > len(seg):
                    continue
                name = seg[i:end]
                if name in _SURFACE_BLOCKLIST:
                    continue
                # 最后一个字是动词/连词/虚词:这是噪音边界,缩回去
                if name[-1] in _NAME_ENDING_NOISE:
                    continue
                # 第二个字也是姓氏:可能是两个相邻角色,取 2 字
                if length == 3 and name[1] in _COMMON_SURNAMES and name[2] not in _NAME_LIKELY_CHARS:
                    continue
                best_name = name
                best_end = end
                break
            if best_name:
                candidates.append(best_name)
                i = best_end
            else:
                i += 1

    # 2. "叫做 XX" / "名叫 XX" 句式(更强信号,即使无常见姓也算)
    for m in re.finditer(r"(?:叫做|名叫|我是|他是|她是|此人乃|乃是)\s*([\u4e00-\u9fa5]{2,4})", text):
        s = m.group(1)
        # 修剪尾部噪音字
        while len(s) > 2 and s[-1] in _NAME_ENDING_NOISE:
            s = s[:-1]
        if s not in _SURFACE_BLOCKLIST and len(s) >= 2:
            candidates.append(s)

    return candidates


# 名字后不太可能跟的字(动词/连词/语气词/虚词等)
_NAME_ENDING_NOISE = set(
    "和与跟同对在了就也都还要去来上下出回开过把被让叫问说看听想又再"
    "突然的地得着是从向往便而则啊呢吗呀哦嗯"
)

# 典型"名"字:出现在多字名末尾的常见字(开放集,启发式)
_NAME_LIKELY_CHARS = set(
    "云风雨雷电火水山川海林森峰岚峻浩然清明哲华瑞祥福禄寿星辰宇宙天地玄"
    "轩昂寒霜雪冰雯婉婷雅静淑慧敏俊杰豪强伟刚毅勇捷敏卓越超凡圣贤儒墨"
    "玉珏珂瑶琪琳琪萱蕊芳菲梅兰竹菊春秋冬夏阳辉煌明亮昭旭旦曦晨"
)


def _find_similar(name: str, known: set[str]) -> str:
    """子串匹配 - 用于识别别名"""
    for k in known:
        if name in k or k in name:
            return k
    return ""


def _score(name: str, count: int, similar: str) -> tuple[float, str]:
    """打分规则:出现频次 + 是否疑似别名

    - 出现 ≥3 且无相似:high confidence new_entity
    - 出现 ≥2 且无相似:medium new_entity
    - 出现 1 次且无相似:低,noise
    - 与已有角色相似:中等 alias
    """
    if similar:
        if count >= 2:
            return 0.65, "alias"
        return 0.4, "alias"

    if count >= 3:
        return 0.85, "new_entity"
    if count == 2:
        return 0.6, "new_entity"
    return 0.25, "noise"
