"""大纲数据模型"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Outline(Base):
    """大纲表"""
    __tablename__ = "outlines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False, comment="大纲标题")
    content = Column(Text, comment="大纲内容")
    structure = Column(Text, comment="结构化大纲数据(JSON)")
    order_index = Column(Integer, comment="排序序号")
    # 卷级契约 - 借鉴 webnovel-writer VolumeBrief,作用于挂在本 Outline 下的所有章节
    creative_brief = Column(JSON, comment="卷级契约(JSON):volume_goal/anti_patterns/required_tropes/pacing")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    def __repr__(self):
        return f"<Outline(id={self.id}, title={self.title})>"