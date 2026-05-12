"""章节 Commit 模型 - 借鉴 webnovel-writer 的不可变 chapter-commit 模式

每次章节内容落库都生成一条 Commit 记录,作为可审计/可回溯的快照:
- content_hash: 内容指纹(SHA-256 前 16 位),用于去重和差异检测
- review_summary: 审稿摘要(各维度问题计数)
- fulfillment: 节点覆盖情况(本次生成覆盖了哪些 CBN/CPN/CEN)
- extraction_meta: 抽取元信息(后续填充)

Commit 行不可变(只 INSERT,不 UPDATE),保证审计可信。
"""
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from app.database import Base
import uuid


class ChapterCommit(Base):
    """章节快照 - 写一次就不再修改(append-only)"""
    __tablename__ = "chapter_commits"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chapter_id = Column(
        String(36),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(50), nullable=False)

    chapter_number = Column(Integer, nullable=False)
    word_count = Column(Integer, nullable=False, default=0)
    content_hash = Column(String(32), nullable=False, comment="内容指纹(SHA-256 前 32 位)")

    review_summary = Column(JSON, nullable=True, comment="审稿摘要: {total, by_severity, by_dimension}")
    fulfillment = Column(JSON, nullable=True, comment="节点覆盖: {covered_nodes, missed_nodes}")
    extraction_meta = Column(JSON, nullable=True, comment="抽取元信息(预留)")
    notes = Column(Text, nullable=True, comment="提交说明(可选)")

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_chapter_commit_chapter_created", "chapter_id", "created_at"),
    )

    def __repr__(self):
        return (
            f"<ChapterCommit(id={self.id[:8]}, chapter_id={self.chapter_id[:8]}, "
            f"hash={self.content_hash[:8]})>"
        )

    def to_dict(self):
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "project_id": self.project_id,
            "chapter_number": self.chapter_number,
            "word_count": self.word_count,
            "content_hash": self.content_hash,
            "review_summary": self.review_summary or {},
            "fulfillment": self.fulfillment or {},
            "extraction_meta": self.extraction_meta or {},
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
