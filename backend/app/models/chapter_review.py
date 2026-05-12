"""章节审稿数据模型 - 存储多维度自动审稿产生的问题列表"""
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.database import Base
import uuid


class ChapterReview(Base):
    """
    章节审稿问题表 - 每条记录代表一条审稿意见

    生命周期: 章节生成完成后由 ChapterReviewHook 触发,后台并发执行 6 个维度审稿器,
    每个维度产出 0..N 条问题,写入本表。同一次审稿用 review_run_id 聚合。

    维度(dimension):
    - consistency: 角色/世界观/职业等级一致性
    - timeline: 时间线/年龄/季节冲突
    - ooc: 角色 Out Of Character
    - continuity: 与上一章衔接断裂
    - logic: 因果/物理/常识漏洞
    - ai_flavor: AI 味(模板化副词、抒情结尾等)

    严重级(severity):
    - info: 提示性
    - warn: 建议修改
    - blocking: 强烈建议重写
    """
    __tablename__ = "chapter_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chapter_id = Column(
        String(36),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(50), nullable=False)
    review_run_id = Column(
        String(36),
        nullable=False,
        index=True,
        comment="同一次审稿批次的所有问题共享此ID,便于按批次过滤/重跑",
    )

    dimension = Column(String(20), nullable=False, comment="审稿维度")
    severity = Column(String(10), nullable=False, default="warn", comment="严重级")
    category = Column(String(50), nullable=True, comment="子分类")

    title = Column(String(200), nullable=False, comment="问题简述")
    evidence = Column(Text, nullable=True, comment="原文证据/引用")
    fix_hint = Column(Text, nullable=True, comment="修改建议")

    status = Column(
        String(20),
        nullable=False,
        default="open",
        index=True,
        comment="状态: open=待处理 / ignored=已忽略 / fixed=已修复",
    )

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_chapter_review_chapter_status", "chapter_id", "status"),
        Index("idx_chapter_review_run", "review_run_id"),
    )

    def __repr__(self):
        return (
            f"<ChapterReview(id={self.id[:8]}, dim={self.dimension}, "
            f"sev={self.severity}, status={self.status})>"
        )

    def to_dict(self):
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "project_id": self.project_id,
            "review_run_id": self.review_run_id,
            "dimension": self.dimension,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "evidence": self.evidence,
            "fix_hint": self.fix_hint,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
