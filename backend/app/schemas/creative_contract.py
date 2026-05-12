"""创作契约 Pydantic Schema"""
from typing import List, Optional

from pydantic import BaseModel, Field


class CreativeContractPayload(BaseModel):
    style_baseline: str = Field("", description="风格底线 - 跨整本书一致的写作特征")
    forbidden_zones: List[str] = Field(default_factory=list, description="禁忌区 - 严禁出现的情节/设定")
    anti_patterns: List[str] = Field(default_factory=list, description="反模式 - 避免的写作套路")
    required_tropes: List[str] = Field(default_factory=list, description="必备桥段 - 类型要求")
    narrative_promises: List[str] = Field(default_factory=list, description="读者承诺 - 长线剧情目标")


class CreativeContractResponse(BaseModel):
    project_id: str
    contract: CreativeContractPayload


class UpdateCreativeContractRequest(BaseModel):
    contract: CreativeContractPayload
