"""一致性审稿器 - 角色/世界观/职业等级一致性"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class ConsistencyReviewer(BaseReviewer):
    dimension = "consistency"
    focus = "角色与世界观一致性"
    criteria = [
        "角色言行是否与已建立的性格/背景一致",
        "角色能力是否超出当前职业等级",
        "世界规则/物理法则/魔法体系是否被违反",
        "角色对其他角色的称呼/关系是否与设定一致",
    ]

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        return f"""【任务】检查第{ctx.chapter_number}章在「{self.focus}」维度的问题。

【项目背景】
书名:{ctx.project_title or '未命名'} | 类型:{ctx.project_genre or '未指定'}
世界观摘要:{ctx.world_setting or '(无)'}

【已知角色设定】
{ctx.characters_info or '(无)'}

【章节正文(第{ctx.chapter_number}章《{ctx.chapter_title}》)】
{ctx.truncated_content()}

请按系统提示词的 JSON 格式输出问题列表。"""
