"""逻辑审稿器 - 因果/物理/常识漏洞"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class LogicReviewer(BaseReviewer):
    dimension = "logic"
    focus = "因果与常识逻辑"
    criteria = [
        "动机不足:角色行动缺乏合理动机",
        "因果断裂:A 事件不能合理导致 B 结果",
        "信息漏洞:角色掌握了他不应知道的信息",
        "物理常识:动作/距离/重量等明显违反常识",
        "便利巧合:依赖低概率巧合推动剧情",
    ]
    max_issues = 4

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        return f"""【任务】检查第{ctx.chapter_number}章在「{self.focus}」维度的问题。

【章节正文】
{ctx.truncated_content()}

关注严重影响可信度的硬伤,不要钻情节深意的牛角尖。
请按系统提示词的 JSON 格式输出。"""
