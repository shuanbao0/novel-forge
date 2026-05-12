"""时间线审稿器 - 时序/年龄/季节冲突"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class TimelineReviewer(BaseReviewer):
    dimension = "timeline"
    focus = "时间线一致性"
    criteria = [
        "事件时间顺序是否合理(不晚于/早于已建立的时间锚点)",
        "角色年龄变化是否符合时间流逝",
        "季节/日夜/天气与前文是否能衔接",
        "回忆/插叙是否标记清晰,不与现实场景混淆",
    ]
    max_issues = 4

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        return f"""【任务】检查第{ctx.chapter_number}章在「{self.focus}」维度的问题。

【已知时间线摘要】
{ctx.timeline_summary or '(无明确时间线记录,聚焦本章内部一致性)'}

【上一章摘要】
{ctx.previous_chapter_summary or '(无)'}

【章节正文(第{ctx.chapter_number}章)】
{ctx.truncated_content()}

请按系统提示词的 JSON 格式输出问题列表。"""
