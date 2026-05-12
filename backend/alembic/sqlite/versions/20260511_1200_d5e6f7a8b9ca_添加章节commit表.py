"""添加章节 commit 表

Revision ID: d5e6f7a8b9ca
Revises: c4d5e6f7a8b9
Create Date: 2026-05-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9ca'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chapter_commits',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('chapter_id', sa.String(), sa.ForeignKey('chapters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('chapter_number', sa.Integer, nullable=False),
        sa.Column('word_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('content_hash', sa.String(), nullable=False),
        sa.Column('review_summary', sa.JSON(), nullable=True),
        sa.Column('fulfillment', sa.JSON(), nullable=True),
        sa.Column('extraction_meta', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_chapter_commits_chapter_id', 'chapter_commits', ['chapter_id'])
    op.create_index('ix_chapter_commits_project_id', 'chapter_commits', ['project_id'])
    op.create_index('idx_chapter_commit_chapter_created', 'chapter_commits', ['chapter_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('idx_chapter_commit_chapter_created', table_name='chapter_commits')
    op.drop_index('ix_chapter_commits_project_id', table_name='chapter_commits')
    op.drop_index('ix_chapter_commits_chapter_id', table_name='chapter_commits')
    op.drop_table('chapter_commits')
