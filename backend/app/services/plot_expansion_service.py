"""大纲剧情展开服务 - 将大纲节点展开为多个章节"""
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json

from app.models.outline import Outline
from app.models.project import Project
from app.models.character import Character
from app.models.chapter import Chapter
from app.services.ai_service import AIService
from app.services.blueprint_validator import BlueprintValidator, BlueprintRejected
from app.services.creative_contract import CreativeContract, VolumeBrief
from app.services.json_helper import loads_json
from app.services.prompt_service import prompt_service, PromptService
from app.logger import get_logger


# 蓝图验证关重试上限. 每次重试都会把上轮违规清单注入 prompt, 让 LLM 修复.
# 最后一次仍失败时, 放行并打 warning, 不阻塞用户主流程(质量降级好过整流程卡死).
MAX_BLUEPRINT_RETRIES = 2


# 让 OUTLINE_EXPAND_* 模板默认产出 scenes 字段, 否则蓝图验证关读 scenes[0].location
# 永远空, 100% 触发兜底错误 → 重试无效 → 最后放行 (= Fix 1 失效).
# scene_instruction 在 <constraints> 段中告诉 LLM 必须输出; scene_field 是 JSON 输出 schema
# 的额外字段, 用逗号开头与前一项目衔接 (模板里写法是 {previous_field}{scene_field}).
_DEFAULT_SCENE_INSTRUCTION = (
    "\n【场景输出硬约束】\n"
    "✅ 每章必须给出 scenes 数组, 至少 1 个对象, 第一个对象的 location 字段必填\n"
    "✅ scenes[0].location 是本章主场景, 必须具体到地点(如 \"教室晚自习\"/\"校门口小摊\"),\n"
    "  不要写 \"学校\"/\"家里\" 这种泛指, 也不要留空\n"
    "✅ scenes[0].location 会被蓝图验证关检查, 同一批次内 ⌈N/3⌉ 个唯一值是硬下限\n"
)
_DEFAULT_SCENE_FIELD = (
    ',\n    "scenes": [\n'
    '      {"location": "主场景的具体地点", "atmosphere": "氛围", "duration": "持续时长"}\n'
    "    ]"
)


def _build_contract_blocks(project: Project, outline: Outline) -> tuple[str, str]:
    """读取项目级 + 卷级契约, 返回可注入 prompt 的两段文本(空则为空串)"""
    project_block = CreativeContract.from_raw(project.creative_contract).to_prompt_block()
    volume_block = VolumeBrief.from_raw(outline.creative_brief).to_prompt_block()
    return project_block, volume_block


def _sanitize_character_beats(raw, character_focus: list) -> list:
    """容错解析 LLM 返回的 character_beats。

    可接受形态:
      - [{"name": "X", "beat": "..."}]  (推荐)
      - {"X": "..."}                     (老式 dict)
      - [{"name": "X", "action": "..."}](字段写错)
    任何无法识别的输入返回空列表(让生成阶段优雅降级)。
    """
    if not raw:
        return []
    result: list[dict] = []
    if isinstance(raw, dict):
        for name, beat in raw.items():
            if name and beat:
                result.append({"name": str(name).strip(), "beat": str(beat).strip()})
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or item.get("character") or "").strip()
            beat = (item.get("beat") or item.get("action") or item.get("note") or "").strip()
            if name and beat:
                result.append({"name": name, "beat": beat})
    return result


def _sanitize_subplot_progression(raw) -> list:
    """容错解析 LLM 返回的 subplot_progression。"""
    if not raw or not isinstance(raw, list):
        return []
    result: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        subplot = (item.get("subplot") or item.get("name") or "").strip()
        step = (item.get("step") or item.get("progress") or "").strip()
        if subplot and step:
            result.append({"subplot": subplot, "step": step})
    return result


def _build_subplot_blocks(project: Project) -> tuple[str, str]:
    """读取项目级支线声明, 返回两段插槽:
       - subplot_field: 注入到 JSON 模板里的额外字段(以逗号开头),
         比如 ',"subplot_progression": [{"subplot": ..., "step": ...}]'
       - subplot_directive: 注入到 constraints 段落的硬指令,
         告诉规划 AI 必须把支线按节奏分布到不同章节
       若项目未声明支线, 两段都返回空串(模板里 {subplot_field}{subplot_directive} 等价无操作)。
    """
    settings = getattr(project, "generation_settings", None) or {}
    if not isinstance(settings, dict):
        return "", ""
    subplots = settings.get("subplots") or []
    if not isinstance(subplots, list):
        return "", ""
    subplots = [s.strip() for s in subplots if isinstance(s, str) and s.strip()]
    if not subplots:
        return "", ""
    field_examples = ",\n".join(
        f'      {{"subplot": "{name}", "step": "本章对该支线的具体推进; 若本章不推进可省略此条"}}'
        for name in subplots
    )
    field_snippet = (
        ',\n    "subplot_progression": [\n'
        f"{field_examples}\n"
        "    ]"
    )
    names = "、".join(subplots)
    directive = (
        "\n【📈 支线推进硬约束】\n"
        f"✅ 项目级支线: {names}\n"
        "✅ 在本批章节里, 每条支线至少推进 1 次(放在合适的章节, 不要全堆在最后一章)\n"
        "✅ subplot_progression 数组只包含本章真实推进的支线; 不推进的支线可省略\n"
        "❌ 严禁连续 5 章对同一支线零推进\n"
    )
    return field_snippet, directive

logger = get_logger(__name__)


class PlotExpansionService:
    """大纲剧情展开服务"""

    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service
        self._validator = BlueprintValidator()

    async def _generate_and_validate(
        self,
        *,
        make_prompt,
        provider: Optional[str],
        model: Optional[str],
        outline_id: str,
        label: str,
    ) -> List[Dict[str, Any]]:
        """LLM 流式生成 + 蓝图验证关 + 失败重试.

        Args:
            make_prompt: 接收 `feedback_block: str` 并返回完整 prompt 的可调用对象.
                         首轮调用传空串, 重试时把上一轮的 BlueprintRejected.to_feedback_block()
                         传入, 让 LLM 看到具体违规项并修复.
            label: 日志用的批次标签, 例 "单批次" / "第 2/3 批".

        Returns: 通过验证(或最后一轮兜底放行)的 chapter_plans 列表.
        """
        feedback_block = ""
        last_plans: List[Dict[str, Any]] = []
        for attempt in range(MAX_BLUEPRINT_RETRIES + 1):
            prompt = make_prompt(feedback_block)
            accumulated_text = ""
            async for chunk in self.ai_service.generate_text_stream(
                prompt=prompt, provider=provider, model=model
            ):
                accumulated_text += chunk
            last_plans = self._parse_expansion_response(accumulated_text, outline_id)
            try:
                self._validator.check(last_plans)
                if attempt > 0:
                    logger.info(f"✅ {label} 蓝图第 {attempt + 1} 轮通过验证")
                return last_plans
            except BlueprintRejected as exc:
                logger.warning(
                    f"⚠️ {label} 蓝图第 {attempt + 1}/{MAX_BLUEPRINT_RETRIES + 1} 轮被拒: "
                    f"{exc}"
                )
                if attempt >= MAX_BLUEPRINT_RETRIES:
                    logger.warning(
                        f"⚠️ {label} 蓝图重试已达上限 {MAX_BLUEPRINT_RETRIES + 1} 次, "
                        f"放行最后一轮结果(质量降级)"
                    )
                    return last_plans
                feedback_block = exc.to_feedback_block()
        return last_plans
    
    async def analyze_outline_for_chapters(
        self,
        outline: Outline,
        project: Project,
        db: AsyncSession,
        target_chapter_count: int = 3,
        expansion_strategy: str = "balanced",
        enable_scene_analysis: bool = True,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: int = 5,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        分析单个大纲,生成多章节规划（支持分批生成）
        
        Args:
            outline: 大纲对象
            project: 项目对象
            db: 数据库会话
            target_chapter_count: 目标生成章节数
            expansion_strategy: 展开策略(balanced/climax/detail)
            enable_scene_analysis: 是否启用场景级分析
            provider: AI提供商
            model: AI模型
            batch_size: 每批生成的章节数（默认5章）
            progress_callback: 进度回调函数(可选)
            
        Returns:
            章节规划列表
        """
        logger.info(f"开始分析大纲 {outline.id}，目标生成 {target_chapter_count} 章")
        
        # 如果章节数较少，直接生成
        if target_chapter_count <= batch_size:
            return await self._generate_chapters_single_batch(
                outline=outline,
                project=project,
                db=db,
                target_chapter_count=target_chapter_count,
                expansion_strategy=expansion_strategy,
                enable_scene_analysis=enable_scene_analysis,
                provider=provider,
                model=model
            )
        
        # 章节数较多，分批生成
        logger.info(f"章节数({target_chapter_count})超过批次大小({batch_size})，启用分批生成")
        return await self._generate_chapters_in_batches(
            outline=outline,
            project=project,
            db=db,
            target_chapter_count=target_chapter_count,
            expansion_strategy=expansion_strategy,
            enable_scene_analysis=enable_scene_analysis,
            provider=provider,
            model=model,
            batch_size=batch_size,
            progress_callback=progress_callback
        )
    
    async def _generate_chapters_single_batch(
        self,
        outline: Outline,
        project: Project,
        db: AsyncSession,
        target_chapter_count: int,
        expansion_strategy: str,
        enable_scene_analysis: bool,
        provider: Optional[str],
        model: Optional[str]
    ) -> List[Dict[str, Any]]:
        """单批次生成章节规划 (含蓝图验证关重试)."""
        # 获取角色信息
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = characters_result.scalars().all()
        characters_info = "\n".join([
            f"- {char.name} ({'组织' if char.is_organization else '角色'}, {char.role_type}): "
            f"{char.personality[:100] if char.personality else '暂无描述'}"
            for char in characters
        ])

        # 获取大纲上下文（前后大纲）
        context_info = await self._get_outline_context(outline, project.id, db)

        # 读取契约 - 项目级 + 卷级
        project_contract_block, volume_brief_block = _build_contract_blocks(project, outline)
        subplot_field, subplot_directive = _build_subplot_blocks(project)

        # 获取自定义提示词模板
        template = await PromptService.get_template("OUTLINE_EXPAND_SINGLE", project.user_id, db)

        def make_prompt(feedback_block: str) -> str:
            # 把验证关反馈前置, 让 LLM 在还没读到主任务时就看到上轮违规
            prefix = f"{feedback_block}\n\n" if feedback_block else ""
            return prefix + PromptService.format_prompt(
                template,
                project_title=project.title,
                project_genre=project.genre or '通用',
                project_theme=project.theme or '未设定',
                project_narrative_perspective=project.narrative_perspective or '第三人称',
                project_world_time_period=project.world_time_period or '未设定',
                project_world_location=project.world_location or '未设定',
                project_world_atmosphere=project.world_atmosphere or '未设定',
                characters_info=characters_info or '暂无角色',
                outline_order_index=outline.order_index,
                outline_title=outline.title,
                outline_content=outline.content,
                context_info=context_info,
                project_contract_block=project_contract_block or "(项目级契约未设置)",
                volume_brief_block=volume_brief_block or "(本卷契约未设置)",
                strategy_instruction=expansion_strategy,
                target_chapter_count=target_chapter_count,
                scene_instruction=_DEFAULT_SCENE_INSTRUCTION,
                scene_field=_DEFAULT_SCENE_FIELD,
                subplot_field=subplot_field,
                subplot_directive=subplot_directive,
            )

        logger.info("调用AI生成章节规划...")
        chapter_plans = await self._generate_and_validate(
            make_prompt=make_prompt,
            provider=provider,
            model=model,
            outline_id=outline.id,
            label="单批次",
        )
        logger.info(f"成功生成 {len(chapter_plans)} 个章节规划")
        return chapter_plans
    
    async def _generate_chapters_in_batches(
        self,
        outline: Outline,
        project: Project,
        db: AsyncSession,
        target_chapter_count: int,
        expansion_strategy: str,
        enable_scene_analysis: bool,
        provider: Optional[str],
        model: Optional[str],
        batch_size: int,
        progress_callback: Optional[callable]
    ) -> List[Dict[str, Any]]:
        """分批生成章节规划（增强差异化版本）"""
        # 计算批次数
        total_batches = (target_chapter_count + batch_size - 1) // batch_size
        logger.info(f"分批生成计划: 总共{target_chapter_count}章，分{total_batches}批，每批{batch_size}章")
        
        # 获取角色信息（所有批次共用）
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = characters_result.scalars().all()
        characters_info = "\n".join([
            f"- {char.name} ({'组织' if char.is_organization else '角色'}, {char.role_type}): "
            f"{char.personality[:100] if char.personality else '暂无描述'}"
            for char in characters
        ])
        
        # 获取大纲上下文
        context_info = await self._get_outline_context(outline, project.id, db)

        # 读取契约 - 项目级 + 卷级(所有批次共用)
        project_contract_block, volume_brief_block = _build_contract_blocks(project, outline)
        subplot_field, subplot_directive = _build_subplot_blocks(project)

        all_chapter_plans = []
        
        # 🔧 收集所有已使用的关键事件，用于防止重复
        used_key_events = set()
        
        for batch_num in range(total_batches):
            # 计算当前批次的章节数
            remaining_chapters = target_chapter_count - len(all_chapter_plans)
            current_batch_size = min(batch_size, remaining_chapters)
            current_start_index = len(all_chapter_plans) + 1
            
            logger.info(f"开始生成第{batch_num + 1}/{total_batches}批，章节范围: {current_start_index}-{current_start_index + current_batch_size - 1}")
            
            # 回调通知进度
            if progress_callback:
                await progress_callback(batch_num + 1, total_batches, current_start_index, current_batch_size)
            
            # 🔧 增强的上下文构建（包含完整的差异化信息）
            previous_context = ""
            if all_chapter_plans:
                # 构建完整的已生成章节摘要（包含关键事件）
                previous_summaries = []
                for ch in all_chapter_plans:  # 显示所有已生成章节
                    key_events_str = "、".join(ch.get('key_events', [])[:3]) if ch.get('key_events') else "无"
                    previous_summaries.append(
                        f"第{ch['sub_index']}节《{ch['title']}》:\n"
                        f"  - 剧情：{ch.get('plot_summary', '')[:150]}\n"
                        f"  - 关键事件：{key_events_str}\n"
                        f"  - 结尾方式：{ch.get('ending_type', '未知')}"
                    )
                
                # 提取所有已使用的关键事件
                all_used_events = []
                for ch in all_chapter_plans:
                    all_used_events.extend(ch.get('key_events', []))
                used_events_str = "、".join(all_used_events[-20:]) if all_used_events else "暂无"
                
                previous_context = f"""
【🔴 已生成章节完整信息（必须参考以确保差异化）】
{chr(10).join(previous_summaries)}

【🔴 已使用的关键事件（本批次不可重复使用）】
{used_events_str}

【🔴 差异化强制要求】
⚠️ 当前是第{current_start_index}-{current_start_index + current_batch_size - 1}节（共{target_chapter_count}节中的第{batch_num + 1}批）
⚠️ 每个新章节必须有完全不同的：
   1. 开场场景（不同地点/时间/人物状态）
   2. 核心事件（不与已生成章节的关键事件重复）
   3. 结尾悬念（不同类型的钩子）
⚠️ 新章节的key_events不得与上面【已使用的关键事件】中的任何事件相同或相似
"""
            # 获取自定义提示词模板
            template = await PromptService.get_template("OUTLINE_EXPAND_MULTI", project.user_id, db)

            # 闭包捕获本批次所有可变量, 给 _generate_and_validate 复用
            _start = current_start_index
            _end = current_start_index + current_batch_size - 1
            _size = current_batch_size
            _prev_ctx = previous_context

            def make_prompt(feedback_block: str, _tmpl=template, _start=_start,
                            _end=_end, _size=_size, _prev=_prev_ctx) -> str:
                prefix = f"{feedback_block}\n\n" if feedback_block else ""
                return prefix + PromptService.format_prompt(
                    _tmpl,
                    project_title=project.title,
                    project_genre=project.genre or '通用',
                    project_theme=project.theme or '未设定',
                    project_narrative_perspective=project.narrative_perspective or '第三人称',
                    project_world_time_period=project.world_time_period or '未设定',
                    project_world_location=project.world_location or '未设定',
                    project_world_atmosphere=project.world_atmosphere or '未设定',
                    characters_info=characters_info or '暂无角色',
                    outline_order_index=outline.order_index,
                    outline_title=outline.title,
                    outline_content=outline.content,
                    context_info=context_info,
                    previous_context=_prev,
                    project_contract_block=project_contract_block or "(项目级契约未设置)",
                    volume_brief_block=volume_brief_block or "(本卷契约未设置)",
                    strategy_instruction=expansion_strategy,
                    start_index=_start,
                    end_index=_end,
                    target_chapter_count=_size,
                    scene_instruction=_DEFAULT_SCENE_INSTRUCTION,
                    scene_field=_DEFAULT_SCENE_FIELD,
                    subplot_field=subplot_field,
                    subplot_directive=subplot_directive,
                )

            logger.info(f"调用AI生成第{batch_num + 1}批...")
            batch_plans = await self._generate_and_validate(
                make_prompt=make_prompt,
                provider=provider,
                model=model,
                outline_id=outline.id,
                label=f"第 {batch_num + 1}/{total_batches} 批",
            )

            # 调整sub_index以保持连续性
            for i, plan in enumerate(batch_plans):
                plan["sub_index"] = current_start_index + i

            all_chapter_plans.extend(batch_plans)

            logger.info(f"第{batch_num + 1}批生成完成，本批生成{len(batch_plans)}章，累计{len(all_chapter_plans)}章")
        
        logger.info(f"分批生成完成，共生成 {len(all_chapter_plans)} 个章节规划")
        return all_chapter_plans
    
    async def batch_expand_outlines(
        self,
        project_id: str,
        db: AsyncSession,
        ai_service: AIService,
        target_chapters_per_outline: int = 3,
        expansion_strategy: str = "balanced",
        provider: Optional[str] = None,
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        批量展开所有大纲为章节
        
        Returns:
            {
                "total_outlines": 总大纲数,
                "total_chapters_planned": 规划的总章节数,
                "expansions": [每个大纲的展开结果]
            }
        """
        logger.info(f"开始批量展开项目 {project_id} 的所有大纲")
        
        # 获取项目
        project_result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise ValueError(f"项目 {project_id} 不存在")
        
        # 获取所有大纲
        outlines_result = await db.execute(
            select(Outline)
            .where(Outline.project_id == project_id)
            .order_by(Outline.order_index)
        )
        outlines = outlines_result.scalars().all()
        
        if not outlines:
            logger.warning(f"项目 {project_id} 没有大纲")
            return {
                "total_outlines": 0,
                "total_chapters_planned": 0,
                "expansions": []
            }
        
        # 逐个展开大纲
        expansions = []
        total_chapters = 0
        
        for outline in outlines:
            try:
                chapter_plans = await self.analyze_outline_for_chapters(
                    outline=outline,
                    project=project,
                    db=db,
                    target_chapter_count=target_chapters_per_outline,
                    expansion_strategy=expansion_strategy,
                    provider=provider,
                    model=model
                )
                
                expansions.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "chapter_plans": chapter_plans,
                    "chapter_count": len(chapter_plans)
                })
                
                total_chapters += len(chapter_plans)
                logger.info(f"大纲 {outline.title} 展开为 {len(chapter_plans)} 章")
                
            except Exception as e:
                logger.error(f"展开大纲 {outline.id} 失败: {str(e)}")
                expansions.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "error": str(e),
                    "chapter_count": 0
                })
        
        # 跨大纲项目级验证: 单 outline 内的 SceneVarietyRule 不能捕捉
        # "3 个 outline 各 4 章但 12 章全在同一场景"这种全局塌缩. 这里只读不写,
        # 发现问题写 warning 到日志和返回结构, 不阻塞 (因为重试要跨多个 outline
        # 重新协调成本太高, 留给用户人工修正).
        try:
            from app.services.blueprint_validator import validate_project_blueprint
            id_to_plans = {
                e["outline_id"]: e["chapter_plans"]
                for e in expansions
                if "chapter_plans" in e
            }
            project_errors = validate_project_blueprint(id_to_plans)
            if project_errors:
                for err in project_errors:
                    logger.warning(f"⚠️ 跨大纲蓝图问题: {err.detail}")
        except Exception as exc:
            logger.warning(f"⚠️ 项目级蓝图验证异常(跳过): {exc}")
            project_errors = []

        result = {
            "total_outlines": len(outlines),
            "total_chapters_planned": total_chapters,
            "expansions": expansions,
            "project_blueprint_warnings": [
                {"rule": e.rule, "detail": e.detail} for e in project_errors
            ],
        }

        logger.info(f"批量展开完成: {len(outlines)} 个大纲 → {total_chapters} 个章节规划")
        return result
    
    async def create_chapters_from_plans(
        self,
        outline_id: str,
        chapter_plans: List[Dict[str, Any]],
        project_id: str,
        db: AsyncSession,
        start_chapter_number: int = None
    ) -> List[Chapter]:
        """
        根据章节规划创建实际的章节记录
        
        Args:
            outline_id: 大纲ID
            chapter_plans: 章节规划列表
            project_id: 项目ID
            db: 数据库会话
            start_chapter_number: 起始章节号（如果为None，则自动计算）
            
        Returns:
            创建的章节列表
        """
        logger.info(f"根据规划创建 {len(chapter_plans)} 个章节记录")

        # 蓝图验证关 - 跑一遍但只打 warning, 不阻塞 (用户手编 plans 时允许通过,
        # 但日志能让我们追踪问题). 与 _generate_and_validate 的"重试 + 兜底放行"
        # 不同, 这里没有 LLM 可以重试.
        try:
            errors = self._validator.validate(chapter_plans)
            if errors:
                logger.warning(
                    f"⚠️ create_chapters_from_plans 检测到蓝图问题(已放行):\n  "
                    + "\n  ".join(e.to_feedback_line() for e in errors)
                )
        except Exception as exc:
            logger.warning(f"⚠️ create_chapters_from_plans 蓝图验证异常(忽略): {exc}")

        # 如果没有指定起始章节号，根据大纲顺序自动计算
        if start_chapter_number is None:
            # 1. 获取当前大纲信息
            outline_result = await db.execute(
                select(Outline).where(Outline.id == outline_id)
            )
            current_outline = outline_result.scalar_one_or_none()
            
            if not current_outline:
                raise ValueError(f"大纲 {outline_id} 不存在")
            
            # 2. 查询所有在当前大纲之前的大纲（按order_index排序）
            prev_outlines_result = await db.execute(
                select(Outline)
                .where(
                    Outline.project_id == project_id,
                    Outline.order_index < current_outline.order_index
                )
                .order_by(Outline.order_index)
            )
            prev_outlines = prev_outlines_result.scalars().all()
            
            # 3. 计算前面所有大纲已展开的章节总数
            total_prev_chapters = 0
            for prev_outline in prev_outlines:
                count_result = await db.execute(
                    select(func.count(Chapter.id))
                    .where(
                        Chapter.project_id == project_id,
                        Chapter.outline_id == prev_outline.id
                    )
                )
                total_prev_chapters += count_result.scalar() or 0
            
            # 4. 起始章节号 = 前面所有大纲的章节数 + 1
            start_chapter_number = total_prev_chapters + 1
            logger.info(f"自动计算起始章节号: {start_chapter_number} (基于大纲order_index={current_outline.order_index}, 前置章节数={total_prev_chapters})")
        
        chapters = []
        for idx, plan in enumerate(chapter_plans):
            # 保存完整的展开规划数据（JSON格式）
            expansion_plan_json = json.dumps({
                "key_events": plan.get("key_events", []),
                "character_focus": plan.get("character_focus", []),
                "character_beats": _sanitize_character_beats(
                    plan.get("character_beats"), plan.get("character_focus", [])
                ),
                "subplot_progression": _sanitize_subplot_progression(
                    plan.get("subplot_progression")
                ),
                "emotional_tone": plan.get("emotional_tone", ""),
                "narrative_goal": plan.get("narrative_goal", ""),
                "conflict_type": plan.get("conflict_type", ""),
                "estimated_words": plan.get("estimated_words", 3000),
                "scenes": plan.get("scenes", []) if plan.get("scenes") else None,
                # 故事内时间锚 - 由 StoryTimelineDecorator 反馈给下章 prompt
                # 旧 expansion_plan 无此键时取空串,Decorator 检测到空就跳过
                "story_time_anchor": (plan.get("story_time_anchor") or "").strip(),
                "story_time_advance": (plan.get("story_time_advance") or "").strip(),
            }, ensure_ascii=False)
            
            chapter = Chapter(
                project_id=project_id,
                outline_id=outline_id,
                chapter_number=start_chapter_number + idx,
                sub_index=plan.get("sub_index", idx + 1),
                title=plan.get("title", f"第{start_chapter_number + idx}章"),
                summary=plan.get("plot_summary", ""),
                expansion_plan=expansion_plan_json,
                status="draft"
            )
            db.add(chapter)
            chapters.append(chapter)
        
        await db.commit()
        
        for chapter in chapters:
            await db.refresh(chapter)
        
        logger.info(f"成功创建 {len(chapters)} 个章节记录（已保存展开规划数据）")
        
        # 重新排序当前大纲之后的所有章节
        await self._renumber_subsequent_chapters(
            project_id=project_id,
            current_outline_id=outline_id,
            db=db
        )
        
        return chapters
    
    async def _get_outline_context(
        self,
        outline: Outline,
        project_id: str,
        db: AsyncSession
    ) -> str:
        """获取大纲的上下文（前后大纲）"""
        # 获取前一个大纲
        prev_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index < outline.order_index
            )
            .order_by(Outline.order_index.desc())
            .limit(1)
        )
        prev_outline = prev_result.scalar_one_or_none()
        
        # 获取后一个大纲
        next_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index > outline.order_index
            )
            .order_by(Outline.order_index)
            .limit(1)
        )
        next_outline = next_result.scalar_one_or_none()
        
        context = ""
        if prev_outline:
            context += f"【前一节】{prev_outline.title}: {prev_outline.content[:200]}...\n\n"
        if next_outline:
            context += f"【后一节】{next_outline.title}: {next_outline.content[:200]}...\n"
        
        return context if context else "（无前后文）"
    
    
    def _parse_expansion_response(
        self,
        ai_response: str,
        outline_id: str
    ) -> List[Dict[str, Any]]:
        """解析AI的展开响应（使用统一的JSON清洗方法，增强差异化字段）"""
        try:
            # 使用统一的JSON清洗方法
            cleaned_text = self.ai_service._clean_json_response(ai_response)
            
            # 解析JSON
            chapter_plans = loads_json(cleaned_text)
            
            # 确保是列表
            if not isinstance(chapter_plans, list):
                chapter_plans = [chapter_plans]
            
            # 为每个章节规划添加outline_id和差异化标识
            for idx, plan in enumerate(chapter_plans):
                plan["outline_id"] = outline_id
                
                # 🔧 确保有 ending_type 字段（用于差异化追踪）
                if "ending_type" not in plan:
                    # 根据叙事目标推断结尾类型
                    narrative_goal = plan.get("narrative_goal", "")
                    if "悬念" in narrative_goal or "疑问" in narrative_goal:
                        plan["ending_type"] = "悬念"
                    elif "冲突" in narrative_goal or "对抗" in narrative_goal:
                        plan["ending_type"] = "冲突升级"
                    elif "转折" in narrative_goal:
                        plan["ending_type"] = "情节转折"
                    elif "情感" in narrative_goal or "情绪" in narrative_goal:
                        plan["ending_type"] = "情感收尾"
                    else:
                        plan["ending_type"] = f"自然过渡-{idx + 1}"
                
                # 🔧 确保 key_events 是列表且非空
                if not plan.get("key_events"):
                    plan["key_events"] = [f"章节{idx + 1}核心事件"]
            
            logger.info(f"✅ 成功解析 {len(chapter_plans)} 个章节规划（含差异化标识）")
            return chapter_plans
            
        except json.JSONDecodeError as e:
            # 解析失败必须抛出,而不是返回一个伪造的"AI解析失败的默认章节"。
            # 旧实现会把这条假章节落库,导出时就会出现在 txt 文件末尾。
            # 让异常向上传播,由批量任务或调用方决定重试 / 中止 / 跳过本批。
            snippet = (ai_response or "")[:500]
            logger.error(f"❌ 解析AI响应失败(outline={outline_id}): {e}, 响应片段: {snippet}")
            raise RuntimeError(
                f"章节规划AI响应JSON解析失败(outline={outline_id}): {e}"
            ) from e
        except Exception as e:
            logger.error(f"❌ 解析异常(outline={outline_id}): {str(e)}")
            raise RuntimeError(
                f"章节规划解析异常(outline={outline_id}): {e}"
            ) from e


    async def _renumber_subsequent_chapters(
        self,
        project_id: str,
        current_outline_id: str,
        db: AsyncSession
    ):
        """
        重新计算当前大纲之后所有大纲的章节序号
        
        Args:
            project_id: 项目ID
            current_outline_id: 当前大纲ID
            db: 数据库会话
        """
        logger.info(f"开始重新排序大纲 {current_outline_id} 之后的所有章节")
        
        # 1. 获取当前大纲信息
        current_outline_result = await db.execute(
            select(Outline).where(Outline.id == current_outline_id)
        )
        current_outline = current_outline_result.scalar_one_or_none()
        
        if not current_outline:
            logger.warning(f"大纲 {current_outline_id} 不存在，跳过重新排序")
            return
        
        # 2. 获取当前大纲及之后的所有大纲（按order_index排序）
        subsequent_outlines_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index >= current_outline.order_index
            )
            .order_by(Outline.order_index)
        )
        subsequent_outlines = subsequent_outlines_result.scalars().all()
        
        # 3. 计算每个大纲的起始章节号
        current_chapter_number = 1
        
        # 先计算前面大纲的章节总数
        prev_outlines_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index < current_outline.order_index
            )
            .order_by(Outline.order_index)
        )
        prev_outlines = prev_outlines_result.scalars().all()
        
        for prev_outline in prev_outlines:
            count_result = await db.execute(
                select(func.count(Chapter.id))
                .where(
                    Chapter.project_id == project_id,
                    Chapter.outline_id == prev_outline.id
                )
            )
            current_chapter_number += count_result.scalar() or 0
        
        # 4. 逐个大纲更新章节序号
        updated_count = 0
        for outline in subsequent_outlines:
            # 获取该大纲的所有章节（按sub_index排序）
            chapters_result = await db.execute(
                select(Chapter)
                .where(
                    Chapter.project_id == project_id,
                    Chapter.outline_id == outline.id
                )
                .order_by(Chapter.sub_index)
            )
            chapters = chapters_result.scalars().all()
            
            # 更新每个章节的chapter_number
            for chapter in chapters:
                if chapter.chapter_number != current_chapter_number:
                    logger.debug(f"更新章节 {chapter.id}: {chapter.chapter_number} -> {current_chapter_number}")
                    chapter.chapter_number = current_chapter_number
                    updated_count += 1
                current_chapter_number += 1
        
        # 5. 提交更新
        await db.commit()
        logger.info(f"重新排序完成，共更新 {updated_count} 个章节的序号")


# 工厂函数
def create_plot_expansion_service(ai_service: AIService) -> PlotExpansionService:
    """创建剧情展开服务实例"""
    return PlotExpansionService(ai_service)
