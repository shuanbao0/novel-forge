"""连续性审稿器 - 与上一章的衔接"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class ContinuityReviewer(BaseReviewer):
    dimension = "continuity"
    focus = "章节衔接"
    criteria = [
        "开篇是否承接上一章结尾的场景/情绪/悬念",
        "上一章遗留的角色处境是否被解释或继续推进",
        "场景切换是否有合理过渡(不要突兀跳转)",
        "上一章埋下的钩子是否被推进或刻意延后",
    ]
    max_issues = 3

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        return f"""【任务】检查第{ctx.chapter_number}章与上一章的衔接。

【上一章摘要】
{ctx.previous_chapter_summary or '(无上一章,本章可能是第一章——若是请返回空数组)'}

【本章正文】
{ctx.truncated_content()}

如果是第一章,直接返回 {{"issues": []}}。
请按系统提示词的 JSON 格式输出。"""
