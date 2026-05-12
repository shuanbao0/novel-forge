"""写作模式抽取器 - 借鉴 webnovel-writer /webnovel-learn

从作者已写的章节里挖出"个人写作特征",存到 project.style_patterns,
后续生成时通过 StylePatternDecorator 注入 prompt,实现风格自一致。

零 LLM 成本(纯统计 + 词频),适合批量、可重跑。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StylePattern:
    avg_sentence_length: int = 0       # 平均句长(汉字数)
    avg_paragraph_length: int = 0      # 平均段长
    dialogue_ratio: float = 0.0        # 对白占比 0-1
    punctuation_density: float = 0.0   # 标点密度(每千字标点数)
    short_sentence_ratio: float = 0.0  # 短句(<15 字)占比
    long_sentence_ratio: float = 0.0   # 长句(>40 字)占比
    favorite_adverbs: list[str] = field(default_factory=list)
    favorite_phrases: list[str] = field(default_factory=list)
    common_openers: list[str] = field(default_factory=list)  # 段首前 4 字 top 5
    rhythm: str = "medium"             # fast/medium/slow
    sample_chapter_count: int = 0
    sample_word_count: int = 0
    extracted_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def is_empty(self) -> bool:
        return self.sample_chapter_count == 0

    def to_prompt_block(self) -> str:
        if self.is_empty():
            return ""
        rhythm_desc = {"fast": "快节奏", "slow": "慢节奏", "medium": "中等节奏"}.get(self.rhythm, self.rhythm)
        lines = [
            "【🪞 作者风格特征 - 请保持一致】",
            f"- 平均句长 {self.avg_sentence_length} 字 / 段长 {self.avg_paragraph_length} 字",
            f"- 对白占比 {self.dialogue_ratio * 100:.0f}% / 节奏 {rhythm_desc}",
            f"- 短句比 {self.short_sentence_ratio * 100:.0f}% / 长句比 {self.long_sentence_ratio * 100:.0f}%",
        ]
        if self.favorite_adverbs:
            lines.append(f"- 作者常用副词:{ '、'.join(self.favorite_adverbs[:5]) }(可酌情沿用)")
        if self.favorite_phrases:
            lines.append(f"- 作者高频短语:{ '、'.join(self.favorite_phrases[:5]) }")
        if self.common_openers:
            lines.append(f"- 段首习惯起势:{ '、'.join(self.common_openers[:3]) }...")
        lines.append(f"- (基于 {self.sample_chapter_count} 章 {self.sample_word_count} 字提取)")
        return "\n".join(lines)


# 中文标点
_PUNCTUATION = "。!?,;:、!?,;:"
_SENT_SPLIT = re.compile(r"[。!?！?\n]+")
_PARA_SPLIT = re.compile(r"\n+")
_DIALOGUE_PATTERN = re.compile(r"[\"""''「」][^\"""''「」]+[\"""''「」]")
# 排除的"AI 味"副词(不计入个人风格)
_BANNED_ADVERBS = {"缓缓", "淡淡", "微微", "默默", "轻轻", "慢慢"}
# 候选副词词典(2-字组合,常见副词/状态修饰词)
_CANDIDATE_ADVERBS = {
    "突然", "猛地", "顿时", "立刻", "瞬间", "随即", "马上", "霎时",
    "悄悄", "偷偷", "径直", "勉强", "其实", "果然", "竟然", "居然",
    "依然", "仍然", "却又", "不禁", "忍不住", "终究", "终于", "起码",
    "似乎", "好像", "也许", "大概", "毕竟", "况且", "甚至", "原来",
}
# 候选高频短语候选(3-4 字)
_PHRASE_LEN = (3, 4)


def extract_from_chapters(
    chapters_text: list[str],
    *,
    sample_limit: int = 20,
    top_n: int = 6,
) -> StylePattern:
    """主入口 - 给定章节正文列表,产出风格特征

    Args:
        chapters_text: 章节正文字符串列表
        sample_limit: 最多分析多少章(取近期 N 章)
        top_n: 各 top 列表保留长度
    """
    if not chapters_text:
        return StylePattern(extracted_at=datetime.now().isoformat())

    samples = [t for t in chapters_text[-sample_limit:] if t and t.strip()]
    if not samples:
        return StylePattern(extracted_at=datetime.now().isoformat())

    full_text = "\n".join(samples)
    total_chars = len(full_text)

    # 1. 句子统计
    sentences = [s.strip() for s in _SENT_SPLIT.split(full_text) if s.strip()]
    sent_lengths = [len(s) for s in sentences] or [0]
    avg_sent = int(sum(sent_lengths) / len(sent_lengths))
    short_ratio = sum(1 for l in sent_lengths if l < 15) / len(sent_lengths)
    long_ratio = sum(1 for l in sent_lengths if l > 40) / len(sent_lengths)

    # 2. 段落统计
    paragraphs = [p.strip() for p in _PARA_SPLIT.split(full_text) if p.strip()]
    para_lengths = [len(p) for p in paragraphs] or [0]
    avg_para = int(sum(para_lengths) / len(para_lengths))

    # 3. 对白占比
    dialogue_chars = sum(len(m.group()) for m in _DIALOGUE_PATTERN.finditer(full_text))
    dialogue_ratio = dialogue_chars / total_chars if total_chars else 0.0

    # 4. 标点密度
    punct_count = sum(1 for c in full_text if c in _PUNCTUATION)
    punct_density = (punct_count / total_chars) * 1000 if total_chars else 0.0

    # 5. 节奏判定
    if avg_sent <= 18 and punct_density >= 80:
        rhythm = "fast"
    elif avg_sent >= 28 and punct_density < 70:
        rhythm = "slow"
    else:
        rhythm = "medium"

    # 6. 高频副词
    adverb_counter = Counter()
    for adv in _CANDIDATE_ADVERBS:
        c = full_text.count(adv)
        if c >= 3:  # 至少出现 3 次才算"偏好"
            adverb_counter[adv] = c
    favorite_adverbs = [w for w, _ in adverb_counter.most_common(top_n) if w not in _BANNED_ADVERBS]

    # 7. 高频短语(3-4 字汉字串,按子串频次)
    phrase_counter = _count_phrases(full_text)
    favorite_phrases = [p for p, _ in phrase_counter.most_common(top_n)]

    # 8. 段首起势(段落前 4 字)
    opener_counter = Counter()
    for para in paragraphs:
        opener = para[:4]
        if opener and re.match(r"^[\u4e00-\u9fa5]+$", opener):
            opener_counter[opener] += 1
    common_openers = [op for op, c in opener_counter.most_common(top_n) if c >= 2]

    return StylePattern(
        avg_sentence_length=avg_sent,
        avg_paragraph_length=avg_para,
        dialogue_ratio=round(dialogue_ratio, 3),
        punctuation_density=round(punct_density, 1),
        short_sentence_ratio=round(short_ratio, 3),
        long_sentence_ratio=round(long_ratio, 3),
        favorite_adverbs=favorite_adverbs,
        favorite_phrases=favorite_phrases,
        common_openers=common_openers,
        rhythm=rhythm,
        sample_chapter_count=len(samples),
        sample_word_count=total_chars,
        extracted_at=datetime.now().isoformat(),
    )


def style_pattern_from_raw(raw: Any) -> StylePattern:
    """从 DB JSON 列复原 StylePattern"""
    if not isinstance(raw, dict):
        return StylePattern(extracted_at="")
    return StylePattern(
        avg_sentence_length=int(raw.get("avg_sentence_length", 0) or 0),
        avg_paragraph_length=int(raw.get("avg_paragraph_length", 0) or 0),
        dialogue_ratio=float(raw.get("dialogue_ratio", 0.0) or 0.0),
        punctuation_density=float(raw.get("punctuation_density", 0.0) or 0.0),
        short_sentence_ratio=float(raw.get("short_sentence_ratio", 0.0) or 0.0),
        long_sentence_ratio=float(raw.get("long_sentence_ratio", 0.0) or 0.0),
        favorite_adverbs=list(raw.get("favorite_adverbs") or []),
        favorite_phrases=list(raw.get("favorite_phrases") or []),
        common_openers=list(raw.get("common_openers") or []),
        rhythm=str(raw.get("rhythm", "medium") or "medium"),
        sample_chapter_count=int(raw.get("sample_chapter_count", 0) or 0),
        sample_word_count=int(raw.get("sample_word_count", 0) or 0),
        extracted_at=str(raw.get("extracted_at", "") or ""),
    )


# === 内部 ===

def _count_phrases(text: str) -> Counter:
    """统计 3-4 字常见中文短语(粗略,不依赖分词)

    剔除明显是动词/连词组合的"伪短语"。
    """
    counter: Counter = Counter()
    # 按非汉字切分
    chunks = re.split(r"[^\u4e00-\u9fa5]+", text)
    for chunk in chunks:
        for length in _PHRASE_LEN:
            for i in range(0, len(chunk) - length + 1):
                phrase = chunk[i : i + length]
                if _is_meaningful_phrase(phrase):
                    counter[phrase] += 1
    # 只保留出现 >= 3 次且字符多样性合格的
    return Counter({p: c for p, c in counter.items() if c >= 3 and len(set(p)) >= 2})


_PHRASE_STOPWORDS = {
    "什么", "怎么", "因为", "所以", "如果", "但是", "可是", "就是", "还是",
    "已经", "现在", "刚才", "突然", "立刻", "马上", "可能", "也许",
}


def _is_meaningful_phrase(phrase: str) -> bool:
    if phrase in _PHRASE_STOPWORDS:
        return False
    if not re.match(r"^[\u4e00-\u9fa5]+$", phrase):
        return False
    # 排除全是停用字组合(单字虚词太多)
    stop_chars = set("的了是和有就在我你他她它这那一个不")
    if sum(1 for c in phrase if c in stop_chars) >= len(phrase) - 1:
        return False
    return True
