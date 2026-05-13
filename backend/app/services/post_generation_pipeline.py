"""章节生成后处理管线 - 用 Pipeline + Hook 模式串联章节落库之后的副作用

设计目标:
- 把原本硬编码在 api/chapters.py event_generator 里的"自动埋伏笔 / 创建分析任务 / 调度后台分析"等步骤抽成可插拔 Hook
- 每个 Hook 内部决定是同步处理还是注册到 background_tasks
- Hook 之间通过 ctx.metadata 单向传递结果(例如 task_id)
- 新增能力(章节审稿、记忆投影等)只需注册新 Hook,不再修改主链

借鉴: webnovel-writer 的 chapter-commit 投影模式
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional, Protocol, runtime_checkable

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger

if False:  # TYPE_CHECKING-style guard - avoid eager model import (循环导入风险)
    from app.services.ai_service import AIService

logger = get_logger(__name__)


@dataclass
class PostGenContext:
    """章节落库后的处理上下文

    schedule() 屏蔽了两种调度方式:
    - SSE 路径: 传入 FastAPI BackgroundTasks,响应后执行
    - 后台任务路径: bg_tasks=None,用 asyncio.create_task 立即调度
    """
    chapter_id: str
    project_id: str
    user_id: str
    chapter_number: int
    chapter_content: str
    db: AsyncSession
    ai_service: "AIService"
    background_tasks: Optional[BackgroundTasks] = None
    metadata: dict = field(default_factory=dict)

    def schedule(self, func: Callable[..., Awaitable], **kwargs) -> None:
        """统一调度后台工作"""
        if self.background_tasks is not None:
            self.background_tasks.add_task(func, **kwargs)
        else:
            asyncio.create_task(func(**kwargs))


@runtime_checkable
class PostGenHook(Protocol):
    """后处理 Hook 协议"""
    name: str

    async def run(self, ctx: PostGenContext) -> None:
        ...


class AutoPlantForeshadowHook:
    """自动标记本章应埋入的伏笔为 planted 状态"""

    name = "auto_plant_foreshadow"

    async def run(self, ctx: PostGenContext) -> None:
        # 延迟导入以避免顶层循环依赖
        from app.services.foreshadow_service import foreshadow_service

        result = await foreshadow_service.auto_plant_pending_foreshadows(
            db=ctx.db,
            project_id=ctx.project_id,
            chapter_id=ctx.chapter_id,
            chapter_number=ctx.chapter_number,
            chapter_content=ctx.chapter_content,
        )
        planted = result.get("planted_count", 0) if result else 0
        if planted > 0:
            logger.info(f"🔮 自动标记伏笔已埋入: {planted}个")
        ctx.metadata["foreshadow_planted_count"] = planted


class CreateAnalysisTaskHook:
    """创建分析任务行,把 task_id 写入 metadata 供下游 Hook 使用"""

    name = "create_analysis_task"

    async def run(self, ctx: PostGenContext) -> None:
        from app.models.analysis_task import AnalysisTask

        task = AnalysisTask(
            chapter_id=ctx.chapter_id,
            user_id=ctx.user_id,
            project_id=ctx.project_id,
            status="pending",
            progress=0,
        )
        ctx.db.add(task)
        await ctx.db.commit()
        await ctx.db.refresh(task)
        ctx.metadata["analysis_task_id"] = task.id
        logger.info(f"📋 已创建分析任务: {task.id}")


class ScheduleAnalysisHook:
    """把后台分析函数挂到 FastAPI BackgroundTasks,响应返回后执行

    依赖: CreateAnalysisTaskHook 必须在它之前注册以写入 analysis_task_id
    """

    name = "schedule_analysis"

    async def run(self, ctx: PostGenContext) -> None:
        task_id = ctx.metadata.get("analysis_task_id")
        if not task_id:
            logger.warning("⚠️ ScheduleAnalysisHook 跳过: 未发现 analysis_task_id")
            return

        # 延迟导入以避免循环依赖(analyze_chapter_background 位于 api 层)
        from app.api.chapters import analyze_chapter_background

        ctx.schedule(
            analyze_chapter_background,
            chapter_id=ctx.chapter_id,
            user_id=ctx.user_id,
            project_id=ctx.project_id,
            task_id=task_id,
            ai_service=ctx.ai_service,
        )
        logger.info(f"⏳ 已调度后台分析任务: {task_id}")


class SyncAnalyzeHook:
    """同步阻塞执行章节分析(批量场景专用)

    与 ScheduleAnalysisHook 的区别:
    - ScheduleAnalysisHook: 通过 ctx.schedule() 异步 fire-and-forget(单章场景适用)
    - SyncAnalyzeHook: 直接 await analyze_chapter_background, 失败抛异常

    批量场景下下一章生成依赖上一章的分析结果(职业更新、记忆投影、剧情连贯),
    必须等本章分析完才能继续,否则下一章上下文质量会断崖式下降。

    重试策略: 不在本 Hook 层做重试 —— PlotAnalyzer.analyze_chapter 内部已有
    3 次指数退避,在外层重复重试会变成 3×3=9 次 LLM 调用,长章节场景下整批
    可能挂十几分钟。失败直接 raise, 由 raise_on_error 把异常上抛, 外层批量
    循环按 task.max_retries 决定是否重试整章。

    依赖: 必须在 CreateAnalysisTaskHook 之后注册以读取 analysis_task_id。
    Pipeline 注册时把本 hook 加入 raise_on_error。
    """

    name = "sync_analyze"

    async def run(self, ctx: PostGenContext) -> None:
        task_id = ctx.metadata.get("analysis_task_id")
        if not task_id:
            raise RuntimeError(
                "SyncAnalyzeHook 缺少 analysis_task_id "
                "(请确保 CreateAnalysisTaskHook 在它之前注册且执行成功)"
            )

        # 延迟导入以避免循环依赖(analyze_chapter_background 位于 api 层)
        from app.api.chapters import analyze_chapter_background

        ok = await analyze_chapter_background(
            chapter_id=ctx.chapter_id,
            user_id=ctx.user_id,
            project_id=ctx.project_id,
            task_id=task_id,
            ai_service=ctx.ai_service,
        )
        if ok:
            ctx.metadata["sync_analyze_ok"] = True
            logger.info(f"✅ 同步章节分析成功: chapter={ctx.chapter_id}")
            return

        raise RuntimeError(
            "章节同步分析失败(PlotAnalyzer 内部 3 次重试均失败), "
            "已请求外层中断整批生成"
        )


class ChapterReviewHook:
    """章节审稿 Hook - 调度多维度审稿(Phase 2)

    非阻塞:审稿是耗时的 LLM 调用,且不影响章节落库,放在 BackgroundTasks 中执行。
    """

    name = "chapter_review"

    async def run(self, ctx: PostGenContext) -> None:
        from app.services.chapter_review_service import run_chapter_review_background

        ctx.schedule(
            run_chapter_review_background,
            chapter_id=ctx.chapter_id,
            project_id=ctx.project_id,
            user_id=ctx.user_id,
            ai_service=ctx.ai_service,
        )
        logger.info(f"⏳ 已调度章节审稿任务: chapter={ctx.chapter_id}")


class CreateChapterCommitHook:
    """章节快照 Hook - 写入不可变 commit 记录(Phase 7)

    阻塞执行,因为它需要在 DB 会话存活期间完成。
    内容哈希用于差异检测和去重。
    """

    name = "create_chapter_commit"

    async def run(self, ctx: PostGenContext) -> None:
        import hashlib
        from app.models.chapter_commit import ChapterCommit
        from app.services.outline_nodes import parse_outline_nodes

        content = ctx.chapter_content or ""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]

        # 节点覆盖计算 - 若 outline 上挂了 nodes,记录哪些被覆盖(简单关键词匹配)
        fulfillment = await _compute_node_fulfillment(ctx)

        commit = ChapterCommit(
            chapter_id=ctx.chapter_id,
            project_id=ctx.project_id,
            user_id=ctx.user_id,
            chapter_number=ctx.chapter_number,
            word_count=len(content),
            content_hash=content_hash,
            fulfillment=fulfillment,
            # review_summary / extraction_meta 由后续 hook 异步填充
            # 这里只建快照
        )
        ctx.db.add(commit)
        await ctx.db.commit()
        ctx.metadata["chapter_commit_id"] = commit.id
        ctx.metadata["content_hash"] = content_hash
        logger.info(f"📦 已建章节快照: commit={commit.id[:8]} hash={content_hash[:8]}")


async def _compute_node_fulfillment(ctx: PostGenContext) -> dict:
    """通过简单子串匹配评估三层节点是否被覆盖

    不依赖 LLM,只做关键词检查。准确率不高但成本为零,作为快照辅助字段。
    """
    from sqlalchemy import select
    from app.models.chapter import Chapter
    from app.models.outline import Outline
    from app.services.outline_nodes import parse_outline_nodes

    try:
        chapter = await ctx.db.get(Chapter, ctx.chapter_id)
        if not chapter or not chapter.outline_id:
            return {}
        outline_result = await ctx.db.execute(
            select(Outline).where(Outline.id == chapter.outline_id)
        )
        outline = outline_result.scalar_one_or_none()
        if not outline:
            return {}
        nodes = parse_outline_nodes(outline.structure)
        if not nodes:
            return {}

        covered: list[str] = []
        missed: list[str] = []
        content = ctx.chapter_content or ""
        for node in nodes:
            key = (node.title or "").strip()
            if key and key in content:
                covered.append(f"[{node.type.value}] {key}")
            else:
                missed.append(f"[{node.type.value}] {key or node.directive[:30]}")
        return {
            "total_nodes": len(nodes),
            "covered_count": len(covered),
            "covered_nodes": covered,
            "missed_nodes": missed,
        }
    except Exception as exc:
        logger.warning(f"⚠️ 节点覆盖计算失败(忽略): {exc}")
        return {}


class PostGenPipeline:
    """章节落库后处理管线

    用法:
        pipeline = PostGenPipeline.default()
        result = await pipeline.execute(ctx)
        # result == ctx.metadata, 包含 analysis_task_id 等
    """

    def __init__(
        self,
        hooks: list[PostGenHook],
        raise_on_error: Optional[set[str]] = None,
    ):
        self.hooks = hooks
        # 关键 hook 名集合: 这些 hook 失败时直接抛出,中断整条管线
        # 其余 hook 失败默认隔离(写入 metadata['hook_errors'])
        self.raise_on_error = raise_on_error or set()

    def register(self, hook: PostGenHook) -> "PostGenPipeline":
        self.hooks.append(hook)
        return self

    async def execute(self, ctx: PostGenContext) -> dict:
        for hook in self.hooks:
            try:
                await hook.run(ctx)
            except Exception as exc:
                logger.warning(f"⚠️ PostGen Hook 失败 [{hook.name}]: {exc}", exc_info=True)
                ctx.metadata.setdefault("hook_errors", []).append({
                    "hook": hook.name,
                    "error": str(exc),
                    "at": datetime.now().isoformat(),
                })
                if hook.name in self.raise_on_error:
                    raise
        return ctx.metadata

    @classmethod
    def default(cls) -> "PostGenPipeline":
        """章节生成后的标准管线(按依赖顺序)

        新增 Hook(如章节审稿、记忆投影)在此追加注册,不需要改动主流程。
        """
        return cls([
            AutoPlantForeshadowHook(),
            CreateChapterCommitHook(),  # 在分析/审稿调度之前快照,保证 hash 稳定
            CreateAnalysisTaskHook(),
            ScheduleAnalysisHook(),
            ChapterReviewHook(),
        ])

    @classmethod
    def for_batch(cls, enable_analysis: bool = True) -> "PostGenPipeline":
        """批量生成场景的管线 - 与单章 default() 拥有相同后处理能力

        与 default() 的关键差异:
        - 用 SyncAnalyzeHook 替换 ScheduleAnalysisHook,把分析改为同步阻塞,
          保证下一章生成时能读到本章的分析结果(职业更新/记忆投影)
        - SyncAnalyzeHook 注册到 raise_on_error,分析失败会中断整批

        当 enable_analysis=False 时只做伏笔埋入 + 快照,跳过分析与审稿。
        """
        if not enable_analysis:
            return cls([
                AutoPlantForeshadowHook(),
                CreateChapterCommitHook(),
            ])
        return cls(
            hooks=[
                AutoPlantForeshadowHook(),
                CreateChapterCommitHook(),
                CreateAnalysisTaskHook(),
                SyncAnalyzeHook(),
                ChapterReviewHook(),
            ],
            raise_on_error={"sync_analyze"},
        )
