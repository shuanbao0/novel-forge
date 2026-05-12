"""AI 味审稿器 - 检测模板化、AI 风格化的写作

借鉴 webnovel-writer/agents/reviewer.md 的 AI 味 5 维度
"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class AIFlavorReviewer(BaseReviewer):
    dimension = "ai_flavor"
    focus = "AI 味检测"
    criteria = [
        "词汇:滥用'缓缓/淡淡/微微/默默'等模板化副词",
        "句法:句式单一,过多对仗工整的并列结构",
        "叙事:开头/结尾模板化(夜幕降临、阳光洒在、章节尾抒情总结)",
        "情感:直白标注情绪('他很愤怒'、'她感到悲伤'),不用动作表现",
        "对话:不同角色说话风格雷同,缺乏个性差异",
    ]
    max_issues = 6

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        return f"""【任务】检测第{ctx.chapter_number}章是否存在 AI 化写作特征。

【章节正文】
{ctx.truncated_content()}

对每条问题:
- category 必须是: vocabulary / syntax / narrative / emotion / dialogue 之一
- evidence 必须摘录最典型的原文片段
- fix_hint 给出具体改写方向(替换为什么/删除什么)

请按系统提示词的 JSON 格式输出。"""
