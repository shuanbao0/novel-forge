"""添加章节审稿表

Revision ID: b2c3d4e5f6a7
Revises: abc12345
Create Date: 2026-05-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'b2c3d4e5f6a7'
down_revision = 'abc12345'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chapter_reviews',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chapter_id', sa.String(36), sa.ForeignKey('chapters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(50), nullable=False),
        sa.Column('review_run_id', sa.String(36), nullable=False, comment='同一次审稿批次的所有问题共享此ID'),
        sa.Column('dimension', sa.String(20), nullable=False, comment='审稿维度'),
        sa.Column('severity', sa.String(10), nullable=False, server_default='warn', comment='严重级'),
        sa.Column('category', sa.String(50), nullable=True, comment='子分类'),
        sa.Column('title', sa.String(200), nullable=False, comment='问题简述'),
        sa.Column('evidence', sa.Text, nullable=True, comment='原文证据/引用'),
        sa.Column('fix_hint', sa.Text, nullable=True, comment='修改建议'),
        sa.Column('status', sa.String(20), nullable=False, server_default='open', comment='状态'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_chapter_reviews_chapter_id', 'chapter_reviews', ['chapter_id'])
    op.create_index('ix_chapter_reviews_project_id', 'chapter_reviews', ['project_id'])
    op.create_index('ix_chapter_reviews_status', 'chapter_reviews', ['status'])
    op.create_index('idx_chapter_review_chapter_status', 'chapter_reviews', ['chapter_id', 'status'])
    op.create_index('idx_chapter_review_run', 'chapter_reviews', ['review_run_id'])


def downgrade() -> None:
    op.drop_index('idx_chapter_review_run', table_name='chapter_reviews')
    op.drop_index('idx_chapter_review_chapter_status', table_name='chapter_reviews')
    op.drop_index('ix_chapter_reviews_status', table_name='chapter_reviews')
    op.drop_index('ix_chapter_reviews_project_id', table_name='chapter_reviews')
    op.drop_index('ix_chapter_reviews_chapter_id', table_name='chapter_reviews')
    op.drop_table('chapter_reviews')
