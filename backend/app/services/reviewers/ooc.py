"""OOC 审稿器 - Out Of Character 检测"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class OOCReviewer(BaseReviewer):
    dimension = "ooc"
    focus = "角色 OOC(性格走样)"
    criteria = [
        "角色说话方式/口头禅是否与已建立人设一致",
        "角色面对冲突的反应是否符合其性格",
        "次要角色是否突然表现出与设定不符的能力或观念",
        "角色之间的相处模式是否与既有关系强度匹配",
    ]
    max_issues = 4

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        return f"""【任务】检查第{ctx.chapter_number}章是否存在角色 OOC(out of character)问题。

【角色设定参考】
{ctx.characters_info or '(无角色资料)'}

【章节正文】
{ctx.truncated_content()}

仅指出与已建立人设明显矛盾的言行,不要质疑作者的合理改写。
请按系统提示词的 JSON 格式输出。"""
