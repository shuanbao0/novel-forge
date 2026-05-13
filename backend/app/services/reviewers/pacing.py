"""节奏审稿器 - 检查叙事推进速度"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class PacingReviewer(BaseReviewer):
    dimension = "pacing"
    focus = "叙事节奏"
    criteria = [
        "信息密度:对话/动作/描写比例失衡",
        "场景拖沓:重复信息、冗余铺垫",
        "节奏过快:关键转折一笔带过,缺乏铺垫和情绪累积",
        "切换粗暴:场景/视角切换缺乏过渡",
        "无效叙述:大段不推动情节的环境描写",
    ]
    max_issues = 4

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        # 卷级 pacing 优先于 genre profile 默认值
        volume_brief = ctx.metadata_extra.get("volume_brief")
        volume_pacing = getattr(volume_brief, "pacing", "") if volume_brief else ""
        pacing_norm = volume_pacing or ctx.metadata_extra.get("genre_pacing") or "medium"
        pacing_source = "本卷契约" if volume_pacing else "本书类型基线"
        return f"""【任务】检查第{ctx.chapter_number}章在「{self.focus}」维度的问题。

【参考】预期目标字数 ~2500-4000 字,关键转折应有 50-200 字铺垫。
【节奏基线 ({pacing_source})】{pacing_norm}(fast=情节驱动/紧凑、medium=情节情感并重、slow=日常细腻)

【章节正文】
{ctx.truncated_content()}

severity 标准:
- blocking: 大段拖沓 / 关键剧情被一句话带过
- warn: 局部节奏问题
- info: 微调建议

请按系统提示词的 JSON 格式输出。"""
