"""事实台账投影 - 从单章分析结果合入项目级台账

为什么单独成服务而不留在 Hook 里:
- SSE 单章生成路径: ScheduleAnalysisHook 异步派发 analyze_chapter_background,
  当时若再用 ExtractFactStateHook 读 DB, 几乎拿不到刚写入的 PlotAnalysis 行
  (background task 还没跑完)
- 批量生成路径: SyncAnalyzeHook 同步等 analyze_chapter_background 完成,
  原本能让 ExtractFactStateHook 工作, 但内部多了一次 DB roundtrip
- 把投影逻辑放进 analyze_chapter_background 内部, 两条路径都能无差别覆盖,
  而且能直接用内存里的 analysis_result, 省一次查询

设计:
- 一个纯函数入口 project_fact_state(...)
- 失败容忍: 任何异常都吞掉(logger.warning), 不影响分析主流程
- 幂等: 同一章节重复调用结果一致 (FactLedger.merge 默认"已有不覆盖")
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.repositories.fact_ledger_repo import FactLedgerRepository
from app.services.fact_ledger import FactDeltas

logger = get_logger(__name__)


async def project_fact_state(
    *,
    db: AsyncSession,
    project_id: str,
    chapter_id: str,
    chapter_number: int,
    character_states: Optional[list],
) -> bool:
    """从 character_states[*].fact_deltas 抽数值/身份事实, 合并到项目台账.

    Returns:
        True 表示有更新, False 表示无变化 / 失败被吞.
    """
    try:
        deltas = FactDeltas.from_character_states(character_states)
        if deltas.is_empty():
            return False
        repo = FactLedgerRepository(db)
        ledger = await repo.get(project_id)
        ledger.merge(deltas)
        ledger.last_chapter_number = max(ledger.last_chapter_number, chapter_number)
        await repo.save(ledger, chapter_id=chapter_id)
        logger.info(
            f"📓 事实台账已更新: 第{chapter_number}章, "
            f"角色增量 {len(deltas.character_deltas)} 个"
        )
        return True
    except Exception as exc:
        logger.warning(
            f"⚠️ 事实台账投影失败(忽略, 不影响分析主流程): "
            f"chapter={chapter_id}, err={exc}"
        )
        return False
