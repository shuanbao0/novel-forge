"""提示词工坊请求 Schema"""
from typing import List, Optional

from pydantic import BaseModel, Field


class ImportRequest(BaseModel):
    """导入提示词请求"""
    custom_name: Optional[str] = Field(None, max_length=100, description="自定义名称")


class PromptSubmissionCreate(BaseModel):
    """提交提示词请求"""
    name: str = Field(..., max_length=100, description="提示词名称")
    description: Optional[str] = Field(None, description="提示词描述")
    prompt_content: str = Field(..., description="提示词内容")
    category: str = Field(default="general", max_length=50, description="分类")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    author_display_name: Optional[str] = Field(None, max_length=100, description="作者显示名")
    is_anonymous: bool = Field(default=False, description="是否匿名发布")
    source_style_id: Optional[int] = Field(None, description="来源写作风格ID")


class ReviewRequest(BaseModel):
    """审核请求"""
    action: str = Field(..., pattern="^(approve|reject)$", description="操作：approve/reject")
    review_note: Optional[str] = Field(None, description="审核备注")
    category: Optional[str] = Field(None, description="分类（可调整）")
    tags: Optional[List[str]] = Field(None, description="标签（可调整）")


class AdminItemCreate(BaseModel):
    """管理员创建提示词"""
    name: str = Field(..., max_length=100, description="提示词名称")
    description: Optional[str] = Field(None, description="提示词描述")
    prompt_content: str = Field(..., description="提示词内容")
    category: str = Field(default="general", description="分类")
    tags: Optional[List[str]] = Field(None, description="标签列表")


class AdminItemUpdate(BaseModel):
    """管理员更新提示词"""
    name: Optional[str] = Field(None, max_length=100, description="提示词名称")
    description: Optional[str] = Field(None, description="提示词描述")
    prompt_content: Optional[str] = Field(None, description="提示词内容")
    category: Optional[str] = Field(None, description="分类")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    status: Optional[str] = Field(None, description="状态")
