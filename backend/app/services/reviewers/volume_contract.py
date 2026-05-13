"""卷契约审稿器 - 检查章节是否违反卷级 brief 中声明的硬约束

数据来源:metadata_extra["volume_brief"] = VolumeBrief 实例
- 触发卷级 anti_patterns -> blocking 或 warn
- 完全未为 required_tropes 中任一项铺设 -> info (单章不需要全推进)
- 与 volume_goal 显著偏题 -> warn
- 情感基调 / 信息密度 与 pacing 严重不符 -> warn

空契约直接返回空数组。
"""
from app.services.creative_contract import VolumeBrief
from app.services.reviewers.base import BaseReviewer, ReviewContext


class VolumeContractReviewer(BaseReviewer):
    dimension = "volume_contract"
    focus = "卷级契约合规性"
    criteria = [
        "本章是否触发卷级 anti_patterns 中任一条",
        "本章是否完全偏离 volume_goal (与本卷叙事目标无关)",
        "本章是否过早消费/破坏 required_tropes 中的桥段",
        "本章节奏与 pacing(fast/medium/slow) 是否严重不符",
    ]
    max_issues = 4

    def get_user_prompt(self, ctx: ReviewContext) -> str:
        brief = ctx.metadata_extra.get("volume_brief")
        if not isinstance(brief, VolumeBrief) or brief.is_empty():
            return (
                f"本章无卷级契约可检查,直接返回 {{\"issues\": []}}。"
                f"章节内容(可忽略): {ctx.truncated_content(limit=200)}"
            )

        volume_title = ctx.metadata_extra.get("volume_title") or "本卷"
        anti = "\n".join(f"- {p}" for p in brief.anti_patterns) or "(无)"
        tropes = "\n".join(f"- {t}" for t in brief.required_tropes) or "(无)"
        pacing_text = {
            "fast": "fast(情节驱动、紧凑推进)",
            "medium": "medium(情节与情感并重)",
            "slow": "slow(细腻铺陈、日常感)",
        }.get(brief.pacing, brief.pacing or "未指定")

        return f"""【任务】检查第{ctx.chapter_number}章是否违反《{volume_title}》卷的契约。

【本卷叙事目标 (volume_goal)】
{brief.volume_goal or "(未声明)"}

【本卷反模式 (anti_patterns) - 严禁触发】
{anti}

【本卷必备桥段 (required_tropes) - 全卷范围内必须推进, 不要求单章铺】
{tropes}

【本卷期望节奏 (pacing)】
{pacing_text}

【本章正文】
{ctx.truncated_content()}

判断准则:
- volume_goal 与本章主线 "无关" 才算偏题(只是没推进 ≠ 偏题, 不报)
- anti_patterns 必须有原文证据才报, 不要风险臆测
- required_tropes 是 "全卷必须" 不是 "本章必须", 单章未铺不报问题, 除非本章在主动破坏该桥段
- pacing 不符指: 卷要求 slow 但本章一句话带过关键事件; 或卷要求 fast 但本章大段静景描写无推进
- evidence 必须摘录章节中违约的原文 (<=80 字)
- fix_hint 必须给出具体改法 (<=120 字)

请按系统提示词的 JSON 格式输出。"""
