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


class TitleRegenerationHook:
    """章节标题重生 Hook - 根据实际正文重新拟标题

    规划阶段的标题往往套路化("X的Y"句式),且不一定贴合最终生成内容。
    本 Hook 在章节落库后调用一次轻量 LLM,基于:
      - 实际正文前 800 字
      - 最近 N 章标题(避重)
      - 原标题(作为兜底,LLM 也可以选择保留)
    生成 6-12 字的新标题。同步执行,保证下一章 recent_chapters_context 读到新值。

    去重策略:
      - 字符 bigram Jaccard 相似度作硬阈值(SIMILARITY_THRESHOLD=0.5)
      - 首次输出与最近章标题相似度过高 → 把违规标题加入 banned, 用更高
        temperature 重试一次。再失败则静默保留原标题。

    任何异常或 LLM 输出不合规时,静默保留原标题。
    """

    name = "title_regeneration"

    LOOKBACK_TITLES = 5
    SIMILARITY_THRESHOLD = 0.5

    async def run(self, ctx: PostGenContext) -> None:
        from sqlalchemy import select
        from app.models.chapter import Chapter

        try:
            chapter = await ctx.db.get(Chapter, ctx.chapter_id)
            if not chapter or not (chapter.content or "").strip():
                return
            current_title = (chapter.title or "").strip()

            # 取最近 N 章标题做避重(不含当前章)
            recent_q = await ctx.db.execute(
                select(Chapter.title)
                .where(Chapter.project_id == ctx.project_id)
                .where(Chapter.chapter_number < ctx.chapter_number)
                .where(Chapter.title.isnot(None))
                .order_by(Chapter.chapter_number.desc())
                .limit(self.LOOKBACK_TITLES)
            )
            recent_titles = [t for (t,) in recent_q.all() if t]
            preview = (ctx.chapter_content or "")[:800].replace("\n", " ")

            new_title = await self._propose_title(
                ctx=ctx,
                current_title=current_title,
                recent_titles=recent_titles,
                preview=preview,
            )
            if new_title is None:
                logger.info(
                    f"⏭️ 标题重生跳过(LLM 两次输出均不合规或相似度过高): "
                    f"chapter={ctx.chapter_number}"
                )
                return

            chapter.title = new_title
            await ctx.db.commit()
            ctx.metadata["title_regenerated"] = True
            ctx.metadata["title_before"] = current_title
            ctx.metadata["title_after"] = new_title
            logger.info(
                f"🏷️ 标题已重生: 第{ctx.chapter_number}章 "
                f"{current_title!r} -> {new_title!r}"
            )
        except Exception as exc:
            logger.warning(f"⚠️ 标题重生失败(忽略): {exc}")

    async def _propose_title(
        self,
        *,
        ctx: PostGenContext,
        current_title: str,
        recent_titles: list[str],
        preview: str,
    ) -> Optional[str]:
        """两轮请求:首轮失败时把违规标题反馈给 LLM 再试一次"""
        banned_extra: list[str] = []
        for attempt in (1, 2):
            raw = await self._request_title_from_llm(
                ctx=ctx,
                current_title=current_title,
                recent_titles=recent_titles,
                preview=preview,
                banned_extra=banned_extra,
                temperature=0.8 if attempt == 1 else 1.0,
            )
            new_title = _normalize_generated_title(raw)
            ok, reason = _is_acceptable_title(
                new_title,
                current_title=current_title,
                recent_titles=recent_titles,
                similarity_threshold=self.SIMILARITY_THRESHOLD,
            )
            if ok:
                return new_title
            logger.info(
                f"♻️ 标题第 {attempt} 轮被拒({reason}): "
                f"chapter={ctx.chapter_number} raw={raw[:40]!r}"
            )
            if new_title:
                banned_extra.append(new_title)
        return None

    @staticmethod
    async def _request_title_from_llm(
        *,
        ctx: PostGenContext,
        current_title: str,
        recent_titles: list[str],
        preview: str,
        banned_extra: list[str],
        temperature: float,
    ) -> str:
        recent_block = "、".join(recent_titles) if recent_titles else "（无）"
        banned_block = (
            "、".join(banned_extra) if banned_extra else "（无）"
        )
        prompt = (
            "为下面这一章重新拟一个 6-12 字的中文标题。\n"
            "要求:\n"
            "1. 具体、有画面、不要使用'X的Y'套路句式\n"
            "2. 不与最近章节标题语义或字面重复(尤其避免共用 2 个以上汉字)\n"
            "3. 直接输出标题,不要任何引号、编号、解释\n\n"
            f"当前标题(可作为参考,但鼓励改写得更精准): {current_title}\n"
            f"最近章节标题(避免重复): {recent_block}\n"
            f"已被拒绝的候选(本轮务必避开): {banned_block}\n\n"
            f"本章正文片段:\n{preview}"
        )
        result = await ctx.ai_service.generate_text(
            prompt=prompt,
            max_tokens=60,
            temperature=temperature,
            auto_mcp=False,
        )
        return (result.get("content") if isinstance(result, dict) else None) or ""


def _normalize_generated_title(raw: str) -> str:
    """剥离 LLM 输出可能附带的引号 / 编号 / 多余说明"""
    s = (raw or "").strip()
    # 去除常见包裹符
    for pair in ("「」", "『』", '""', "''", "《》", "()", "（）", "[]", "【】"):
        if len(s) >= 2 and s[0] == pair[0] and s[-1] == pair[1]:
            s = s[1:-1].strip()
    # LLM 偶尔输出多行,取首行
    if "\n" in s:
        s = s.splitlines()[0].strip()
    # 去除常见前缀 "标题:" "新标题:"
    for prefix in ("标题:", "标题：", "新标题:", "新标题：", "Title:", "title:"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
    return s


def _title_bigrams(s: str) -> set[str]:
    """字符 bigram - 短中文标题做相似度的最稳定特征"""
    s = (s or "").strip()
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _title_similarity(a: str, b: str) -> float:
    """字符 bigram Jaccard 相似度,适合 6-12 字短中文标题"""
    if not a or not b:
        return 0.0
    ba, bb = _title_bigrams(a), _title_bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def _shared_affix_len(a: str, b: str, *, side: str) -> int:
    """两个串共享的前缀或后缀字符数"""
    if not a or not b:
        return 0
    n = min(len(a), len(b))
    if side == "suffix":
        i = 0
        while i < n and a[-1 - i] == b[-1 - i]:
            i += 1
        return i
    if side == "prefix":
        i = 0
        while i < n and a[i] == b[i]:
            i += 1
        return i
    raise ValueError(side)


def _is_acceptable_title(
    new_title: str,
    *,
    current_title: str,
    recent_titles: list[str] = (),
    similarity_threshold: float = 0.45,
    affix_threshold: int = 3,
) -> tuple[bool, str]:
    """新标题校验:长度 + 不与原标题等价 + 与近期标题相似度低于阈值

    两层去重:
      1. bigram Jaccard ≥ similarity_threshold → 整体过近
      2. 共享前/后缀 ≥ affix_threshold 字 → 句式套路撞车
         (例:"黑板倒数三十天" 与 "粉笔敲响三十天" 共享后缀 "三十天" 3 字)

    返回 (是否通过, 不通过原因) - 原因字符串供日志定位。
    """
    if not new_title:
        return False, "空标题"
    n = len(new_title)
    if n < 4 or n > 16:
        return False, f"长度 {n} 超出 4-16"
    if new_title == current_title:
        return False, "与原标题相同"
    for t in recent_titles or ():
        if not t:
            continue
        sim = _title_similarity(new_title, t)
        if sim >= similarity_threshold:
            return False, f"与《{t}》bigram 相似度 {sim:.2f}≥{similarity_threshold}"
        suf = _shared_affix_len(new_title, t, side="suffix")
        if suf >= affix_threshold:
            return False, f"与《{t}》共享后缀 {suf} 字"
        pre = _shared_affix_len(new_title, t, side="prefix")
        if pre >= affix_threshold:
            return False, f"与《{t}》共享前缀 {pre} 字"
    return True, ""


class MotifExtractionHook:
    """已用意象抽取 Hook - 把本章 3-5 个标志性意象 / 口头禅写入 StoryMemory

    数据回流路径:
      生成正文 -> 本 Hook 调 LLM 抽取 -> MotifRepository.record()
        -> 下一章生成时 MotifCoolingDecorator 读出
        -> 注入下章 prompt 的"冷却 / 禁用"段落

    Phase 3 引入。Hook 抢在 CreateAnalysisTaskHook 之后跑,但失败不影响主流程。
    """

    name = "motif_extraction"

    MAX_MOTIFS = 5

    async def run(self, ctx: PostGenContext) -> None:
        try:
            from app.repositories.motif_repo import MotifRepository
        except ImportError:
            return
        try:
            preview = (ctx.chapter_content or "")[:1500].replace("\n", " ")
            if not preview.strip():
                return
            prompt = (
                "从下面的小说章节正文中抽取本章最具标志性的 3-5 个元素,用于后续章节去重。\n"
                "元素类别包括: 口头禅、反复出现的意象、场景特征词、人物标志动作。\n"
                "每个元素 2-6 个字,直接输出 JSON 数组,不要任何解释,例:\n"
                '["红榜见", "消毒水味", "粉笔灰"]\n\n'
                f"正文片段:\n{preview}"
            )
            result = await ctx.ai_service.generate_text(
                prompt=prompt,
                max_tokens=200,
                temperature=0.3,
                auto_mcp=False,
            )
            raw = (result.get("content") if isinstance(result, dict) else None) or ""
            motifs = _parse_motif_list(raw)
            if not motifs:
                return
            repo = MotifRepository(ctx.db)
            recorded = await repo.record_batch(
                project_id=ctx.project_id,
                chapter_id=ctx.chapter_id,
                chapter_number=ctx.chapter_number,
                motifs=motifs[: self.MAX_MOTIFS],
            )
            ctx.metadata["motifs_recorded"] = recorded
            logger.info(
                f"♻️ 已记录本章意象: chapter={ctx.chapter_number} count={recorded}"
            )
        except Exception as exc:
            logger.warning(f"⚠️ 意象抽取失败(忽略): {exc}")


def _parse_motif_list(raw: str) -> list[str]:
    """从 LLM 输出中解析 motif 列表。鲁棒处理 JSON 数组及容错回退到逗号分隔。"""
    import json
    s = (raw or "").strip()
    if not s:
        return []
    # 剥离 ```json ... ``` 包裹
    if s.startswith("```"):
        lines = [l for l in s.splitlines() if not l.strip().startswith("```")]
        s = "\n".join(lines).strip()
    # 优先尝试 JSON 数组
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except (ValueError, TypeError):
        pass
    # 回退:逗号 / 顿号 分隔
    parts = []
    for raw_part in s.replace("、", ",").replace("，", ",").split(","):
        cleaned = raw_part.strip().strip('"\'「」『』《》[]()')
        if cleaned and len(cleaned) <= 20:
            parts.append(cleaned)
    return parts


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

        Hook 顺序的依赖关系:
        - AutoPlantForeshadow: 不依赖 title/commit, 可在最前
        - CreateChapterCommit: 用 chapter_content 算 hash, 不依赖 title
        - TitleRegeneration: 改 chapter.title, 让后续分析 / 下章上下文用上新标题
        - MotifExtraction: 不阻塞主流程, 失败容忍, 但其结果影响下一章 prompt
        - CreateAnalysisTask + ScheduleAnalysis: 分析后台跑
        - ChapterReview: 审稿后台跑
        """
        return cls([
            AutoPlantForeshadowHook(),
            CreateChapterCommitHook(),
            TitleRegenerationHook(),
            MotifExtractionHook(),
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

        当 enable_analysis=False 时只做伏笔埋入 + 快照 + 标题 + 意象去重,
        跳过分析与审稿。
        """
        if not enable_analysis:
            return cls([
                AutoPlantForeshadowHook(),
                CreateChapterCommitHook(),
                TitleRegenerationHook(),
                MotifExtractionHook(),
            ])
        return cls(
            hooks=[
                AutoPlantForeshadowHook(),
                CreateChapterCommitHook(),
                TitleRegenerationHook(),
                MotifExtractionHook(),
                CreateAnalysisTaskHook(),
                SyncAnalyzeHook(),
                ChapterReviewHook(),
            ],
            raise_on_error={"sync_analyze"},
        )
