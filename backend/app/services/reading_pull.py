"""读者抓力评分 - 借鉴 webnovel-writer reading-pull 指标

零 LLM 成本的启发式评分(0-100),输入:
- 章节正文(用于结构特征)
- 审稿 issues(用于扣分)
- 抽取事件(用于加分)
- Genre Profile(用于基线对齐)

输出一个 score + 详细分项,落到 ChapterCommit.extraction_meta.reading_pull。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReadingPullScore:
    score: int = 0                # 最终分数 0-100
    grade: str = "C"              # S/A/B/C/D
    breakdown: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "breakdown": self.breakdown,
            "issues": self.issues,
        }


def compute(
    *,
    content: str,
    review_issues: list[dict] | None = None,
    events: list[dict] | None = None,
    hook_density_baseline: int = 2,
    reading_pull_floor: int = 60,
) -> ReadingPullScore:
    """计算章节抓力分数

    评分逻辑(满分 100):
    - 基础分: 60
    - 钩子密度达标: +15
    - 开头钩子(前 200 字含问句/动作起势/对话起势): +5
    - 结尾钩子(末 200 字含未完成/未解之谜/动作中断): +10
    - 对白比 ≥ 25%: +5
    - 段落长度合理(平均 80-220 字): +5
    - 阻塞级 review 问题: 每个 -8
    - warn 级 review 问题: 每个 -3
    - 章节字数 < 1500 或 > 6000: -5
    """
    content = content or ""
    word_count = len(content)
    breakdown: dict = {}
    issues: list[str] = []

    base = 60
    breakdown["base"] = base

    # 1. 字数
    if 1500 <= word_count <= 6000:
        breakdown["word_count_ok"] = 0
    else:
        breakdown["word_count_penalty"] = -5
        issues.append(f"字数 {word_count} 超出合理区间 [1500, 6000]")

    # 2. 钩子密度估计 - 用问号、未完成符、悬念词
    hook_signals = (
        content.count("?") + content.count("？")
        + content.count("……") + content.count("...")
        + sum(content.count(k) for k in ["突然", "竟然", "猛地", "谁也没想到", "却"])
    )
    expected_hooks = max(1, (word_count // 1000) * hook_density_baseline)
    if hook_signals >= expected_hooks:
        breakdown["hook_density"] = 15
    elif hook_signals >= expected_hooks // 2:
        breakdown["hook_density"] = 8
    else:
        breakdown["hook_density"] = 0
        issues.append(f"钩子信号 {hook_signals} 低于本类型基线 {expected_hooks}")

    # 3. 开头钩子
    head = content[:200]
    if any(p in head for p in ["?", "？", "!", "！"]) or _has_action_opener(head):
        breakdown["opening_hook"] = 5
    else:
        breakdown["opening_hook"] = 0

    # 4. 结尾钩子
    tail = content[-200:] if len(content) > 200 else content
    if any(p in tail for p in ["?", "？", "……", "..."]) or _is_unresolved_ending(tail):
        breakdown["ending_hook"] = 10
    else:
        breakdown["ending_hook"] = 0
        issues.append("结尾缺乏明显钩子(无问句/省略号/未完成动作)")

    # 5. 对白比
    dialogue_chars = sum(1 for c in content if c in '"""''')
    dialogue_ratio = dialogue_chars / (word_count * 2) if word_count else 0  # 配对引号
    if dialogue_ratio >= 0.06:
        breakdown["dialogue_ratio"] = 5
    else:
        breakdown["dialogue_ratio"] = 0

    # 6. 段落长度
    paragraphs = [p for p in content.split("\n") if p.strip()]
    if paragraphs:
        avg_para = sum(len(p) for p in paragraphs) / len(paragraphs)
        if 80 <= avg_para <= 220:
            breakdown["paragraph_size"] = 5
        else:
            breakdown["paragraph_size"] = 0
            if avg_para > 220:
                issues.append(f"段落平均 {avg_para:.0f} 字过长,影响阅读")
    else:
        breakdown["paragraph_size"] = 0

    # 7. 审稿问题扣分
    if review_issues:
        blocking_count = sum(1 for i in review_issues if i.get("severity") == "blocking")
        warn_count = sum(1 for i in review_issues if i.get("severity") == "warn")
        penalty = blocking_count * 8 + warn_count * 3
        breakdown["review_penalty"] = -penalty
    else:
        breakdown["review_penalty"] = 0

    # 8. 事件密度加分(有抽取事件说明剧情推进充实)
    if events:
        if len(events) >= 3:
            breakdown["event_density"] = 5
        elif len(events) >= 1:
            breakdown["event_density"] = 2
        else:
            breakdown["event_density"] = 0
    else:
        breakdown["event_density"] = 0

    score = sum(breakdown.values())
    score = max(0, min(100, score))

    if score >= 90:
        grade = "S"
    elif score >= 80:
        grade = "A"
    elif score >= reading_pull_floor:
        grade = "B"
    elif score >= reading_pull_floor - 15:
        grade = "C"
    else:
        grade = "D"

    return ReadingPullScore(score=score, grade=grade, breakdown=breakdown, issues=issues)


def _has_action_opener(text: str) -> bool:
    """开头是否为动作起势"""
    opener_words = ["他", "她", "我", "门", "刀", "剑", "脚", "手"]
    if not text:
        return False
    return any(text.lstrip().startswith(w) for w in opener_words)


def _is_unresolved_ending(text: str) -> bool:
    """结尾是否为未完成"""
    if not text:
        return False
    stripped = text.rstrip()
    if not stripped:
        return False
    last_char = stripped[-1]
    # 句号/感叹号结尾 = 完结陈述,不算钩子
    if last_char in "。.!！":
        return False
    return True
