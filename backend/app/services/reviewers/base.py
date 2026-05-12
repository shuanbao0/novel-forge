"""审稿器基类与共用数据结构"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from app.logger import get_logger
from app.services.json_helper import parse_json

if TYPE_CHECKING:
    from app.services.ai_service import AIService

logger = get_logger(__name__)


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCKING = "blocking"


@dataclass
class ReviewContext:
    """审稿上下文 - 一次审稿运行所需的全部素材

    构建方式见 ReviewContextBuilder(独立于 chapter_context_service,避免污染章节生成路径)
    """
    chapter_id: str
    chapter_number: int
    chapter_title: str
    chapter_content: str
    project_title: str = ""
    project_genre: str = ""
    project_theme: str = ""
    narrative_perspective: str = "第三人称"
    # 前置素材
    previous_chapter_summary: str = ""
    characters_info: str = ""
    world_setting: str = ""
    foreshadow_summary: str = ""
    timeline_summary: str = ""

    # 结构化扩展数据 - Reviewer 子类可读特定键(如 narrative_promises)
    metadata_extra: dict = field(default_factory=dict)

    def truncated_content(self, limit: int = 6000) -> str:
        return self.chapter_content[:limit] if len(self.chapter_content) > limit else self.chapter_content


@dataclass
class ReviewIssue:
    """单条审稿意见"""
    dimension: str
    severity: str
    title: str
    evidence: str = ""
    fix_hint: str = ""
    category: str = ""

    @classmethod
    def from_dict(cls, dimension: str, data: dict) -> "ReviewIssue":
        return cls(
            dimension=dimension,
            severity=str(data.get("severity") or Severity.WARN.value).lower(),
            title=str(data.get("title", "")).strip(),
            evidence=str(data.get("evidence", "")).strip(),
            fix_hint=str(data.get("fix_hint", "")).strip(),
            category=str(data.get("category", "")).strip(),
        )

    def is_valid(self) -> bool:
        return bool(self.title) and self.severity in {s.value for s in Severity}


class BaseReviewer(ABC):
    """单维度审稿器基类

    子类只需声明 dimension/focus/criteria,共用的 LLM 调用 + JSON 解析逻辑在基类完成。
    """

    dimension: ClassVar[str]
    focus: ClassVar[str]
    criteria: ClassVar[list[str]] = []
    max_issues: ClassVar[int] = 5

    def __init__(self, ai_service: "AIService", max_tokens: int = 1500):
        self.ai_service = ai_service
        self.max_tokens = max_tokens

    @abstractmethod
    def get_user_prompt(self, ctx: ReviewContext) -> str:
        """子类实现:基于 ctx 构造该维度的用户提示词"""
        ...

    def get_system_prompt(self) -> str:
        criteria_text = "\n".join(f"- {c}" for c in self.criteria) or "- 自由判断"
        return (
            f"你是资深小说编辑,专精于「{self.focus}」维度的审稿。\n"
            f"你只检查当前维度的问题,不评论其他方面。\n\n"
            f"【审查要点】\n{criteria_text}\n\n"
            f"【严重级标准】\n"
            f"- blocking: 严重错误,会破坏读者沉浸感,必须修改\n"
            f"- warn: 明显瑕疵,建议修改\n"
            f"- info: 可优化,但不影响阅读\n\n"
            f"【输出要求】\n"
            f"- 严格的 JSON 格式,不要 markdown 包裹\n"
            f"- 最多输出 {self.max_issues} 个最重要的问题\n"
            f"- 没有问题就返回空数组\n"
            f'- 输出结构: {{"issues": [{{"severity":"warn","category":"...","title":"...","evidence":"原文摘录(<=80字)","fix_hint":"具体改法(<=120字)"}}]}}'
        )

    async def review(self, ctx: ReviewContext) -> list[ReviewIssue]:
        """运行该维度的审稿,返回 issue 列表(失败时返回空列表,不抛异常)"""
        try:
            response = await self.ai_service.generate_text(
                prompt=self.get_user_prompt(ctx),
                system_prompt=self.get_system_prompt(),
                max_tokens=self.max_tokens,
                auto_mcp=False,
            )
            content = response.get("content", "") if isinstance(response, dict) else ""
            if not content:
                return []
            data = parse_json(content)
            raw_issues = data.get("issues", []) if isinstance(data, dict) else []
            issues = [
                ReviewIssue.from_dict(self.dimension, raw)
                for raw in raw_issues
                if isinstance(raw, dict)
            ]
            return [i for i in issues if i.is_valid()][: self.max_issues]
        except Exception as exc:
            logger.warning(f"⚠️ Reviewer[{self.dimension}] 失败: {exc}")
            return []
