"""读者抓力审稿器 - 检查章节钩子强度和阅读吸引力

借鉴 webnovel-writer 的 reader-pull reviewer
"""
from app.services.reviewers.base import BaseReviewer, ReviewContext


class ReaderPullReviewer(BaseReviewer):
    dimension = "reader_pull"
    focus = "读者抓力(继续阅读的欲望)"
    criteria = [
        "开篇钩子:前 200 字是否能勾住读者继续读下去",
        "结尾钩子:结尾是否埋下让读者必须看下一章的悬念",
        "中段钩子:每 500-800 字应有一个小钩子防止读者跳出",
        "情绪共鸣:读者能否对主角处境产生代入感",
        "信息差吸引:是否制造'读者比角色多知道'或'角色比读者多知道'的张力",
    ]
    max_issues = 4

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        hook_density = ctx.metadata_extra.get("genre_hook_density") or 2
        return f"""【任务】评估第{ctx.chapter_number}章的「{self.focus}」。
【本书类型钩子密度基线】每千字应有约 {hook_density} 个钩子。

把自己当成第一次读这本书的读者,判断:
- 读完后会不会想继续读下一章?
- 中间会不会想跳出去做别的事?
- 哪些地方"抓住了"读者,哪些地方"放走了"读者?

【章节正文】
{ctx.truncated_content()}

evidence 必须摘录"放走读者"的具体段落,fix_hint 给出加钩子的具体改法。

severity 标准:
- blocking: 结尾完全没钩子 / 开篇 200 字毫无吸引力
- warn: 中段抓力不足
- info: 可以更抓人

请按系统提示词的 JSON 格式输出。"""
