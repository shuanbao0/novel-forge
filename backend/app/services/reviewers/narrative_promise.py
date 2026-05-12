"""读者承诺审稿器 - 检查章节是否违背或冷处理了项目级长线承诺

承诺来源:项目 creative_contract.narrative_promises
- 如果章节明显违背承诺(如承诺主角终将获胜,但本章直接战死),给 blocking
- 如果承诺已被冷处理 N 章未推进,给 warn
- 否则不报问题(承诺只在违背时触发)
"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class NarrativePromiseReviewer(BaseReviewer):
    dimension = "narrative_promise"
    focus = "读者承诺(长线契约)"
    criteria = [
        "本章剧情是否与项目级读者承诺存在直接矛盾",
        "本章是否让承诺彻底失效(角色死亡/能力失去/目标放弃)",
        "本章是否冷处理了长线承诺(完全不推进)",
        "本章是否过早兑现了应保留到结局的承诺",
    ]
    max_issues = 3

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        promises = ctx.metadata_extra.get("narrative_promises") or []
        if not promises:
            promises_text = "(本项目未声明读者承诺,直接返回 {\"issues\": []})"
        else:
            promises_text = "\n".join(f"- {p}" for p in promises)

        return f"""【任务】检查第{ctx.chapter_number}章是否违背或不当处理项目级读者承诺。

【项目级读者承诺】
{promises_text}

【本章正文】
{ctx.truncated_content()}

判断准则:
- 如果项目无承诺,直接返回 {{"issues": []}}
- 只在明显违背/直接矛盾时报告;承诺不需要每章推进
- evidence 必须摘录章节中违背承诺的原文
- fix_hint 必须指出如何修改才能不违背承诺

请按系统提示词的 JSON 格式输出。"""
