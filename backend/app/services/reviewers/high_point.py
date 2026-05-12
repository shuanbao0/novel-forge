"""高潮点审稿器 - 检查情绪高点的兑现强度

借鉴 webnovel-writer 的 high-point reviewer
"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class HighPointReviewer(BaseReviewer):
    dimension = "high_point"
    focus = "高潮点兑现"
    criteria = [
        "本章预设的情绪高点(冲突/反转/揭示)是否充分展开",
        "高潮缺乏铺垫:情绪累积不足就强行爆发",
        "高潮过早收尾:刚到爆点就匆匆结束",
        "情绪曲线平坦:没有清晰的起承转合",
        "高潮被次要情节稀释:多线并行模糊了焦点",
    ]
    max_issues = 3

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        return f"""【任务】评估第{ctx.chapter_number}章「{self.focus}」是否到位。

每个章节应有 1-2 个明确的情绪高点(可以是冲突爆发、关键揭示、情感顶峰),
本审稿专门检查:高点是否真的"高"——铺垫够不够、爆发够不够、回响够不够。

【章节正文】
{ctx.truncated_content()}

severity 标准:
- blocking: 本章完全没有任何情绪高点 / 高点被严重稀释
- warn: 高点存在但兑现不足
- info: 可以更强烈

请按系统提示词的 JSON 格式输出。如本章是过渡章无需高点,返回 {{"issues": []}}。"""
