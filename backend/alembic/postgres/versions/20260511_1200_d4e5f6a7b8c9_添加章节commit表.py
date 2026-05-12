"""添加章节 commit 表

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chapter_commits',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chapter_id', sa.String(36), sa.ForeignKey('chapters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(50), nullable=False),
        sa.Column('chapter_number', sa.Integer, nullable=False),
        sa.Column('word_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('content_hash', sa.String(32), nullable=False),
        sa.Column('review_summary', JSONB, nullable=True),
        sa.Column('fulfillment', JSONB, nullable=True),
        sa.Column('extraction_meta', JSONB, nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_chapter_commits_chapter_id', 'chapter_commits', ['chapter_id'])
    op.create_index('ix_chapter_commits_project_id', 'chapter_commits', ['project_id'])
    op.create_index('idx_chapter_commit_chapter_created', 'chapter_commits', ['chapter_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('idx_chapter_commit_chapter_created', table_name='chapter_commits')
    op.drop_index('ix_chapter_commits_project_id', table_name='chapter_commits')
    op.drop_index('ix_chapter_commits_chapter_id', table_name='chapter_commits')
    op.drop_table('chapter_commits')
