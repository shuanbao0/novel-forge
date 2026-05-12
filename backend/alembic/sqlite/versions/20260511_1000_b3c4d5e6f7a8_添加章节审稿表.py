"""添加章节审稿表

Revision ID: b3c4d5e6f7a8
Revises: def45678ghi9
Create Date: 2026-05-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'b3c4d5e6f7a8'
down_revision = 'def45678ghi9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chapter_reviews',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('chapter_id', sa.String(), sa.ForeignKey('chapters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('review_run_id', sa.String(), nullable=False),
        sa.Column('dimension', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False, server_default='warn'),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('fix_hint', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
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
