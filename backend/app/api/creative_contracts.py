"""创作契约 API - 读/写项目级硬约束"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.database import get_db
from app.logger import get_logger
from app.models.project import Project
from app.schemas.creative_contract import (
    CreativeContractPayload,
    CreativeContractResponse,
    UpdateCreativeContractRequest,
)
from app.services.creative_contract import CreativeContract

router = APIRouter(prefix="/projects", tags=["创作契约"])
logger = get_logger(__name__)


@router.get(
    "/{project_id}/creative-contract",
    response_model=CreativeContractResponse,
    summary="读取项目的创作契约",
)
async def get_creative_contract(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    contract = CreativeContract.from_raw(project.creative_contract)
    return CreativeContractResponse(
        project_id=project_id,
        contract=CreativeContractPayload(**contract.to_dict()),
    )


@router.put(
    "/{project_id}/creative-contract",
    response_model=CreativeContractResponse,
    summary="更新项目的创作契约",
)
async def update_creative_contract(
    project_id: str,
    payload: UpdateCreativeContractRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    contract = CreativeContract(
        style_baseline=payload.contract.style_baseline,
        forbidden_zones=payload.contract.forbidden_zones,
        anti_patterns=payload.contract.anti_patterns,
        required_tropes=payload.contract.required_tropes,
        narrative_promises=payload.contract.narrative_promises,
    )
    project.creative_contract = contract.to_dict()
    await db.commit()
    logger.info(f"📜 项目 {project_id} 契约已更新")
    return CreativeContractResponse(
        project_id=project_id,
        contract=CreativeContractPayload(**contract.to_dict()),
    )
