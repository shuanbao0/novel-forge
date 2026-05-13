"""为 batch_generation_tasks 增加章节级实时进度字段

Revision ID: a7b8c9d0e1fc
Revises: f5a6b7c8d9eb
Create Date: 2026-05-13 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1fc'
down_revision = 'f5a6b7c8d9eb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'batch_generation_tasks',
        sa.Column('current_chapter_chars', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'batch_generation_tasks',
        sa.Column('current_chapter_target_chars', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'batch_generation_tasks',
        sa.Column('current_chapter_phase', sa.String(length=20), nullable=False, server_default='waiting'),
    )


def downgrade() -> None:
    op.drop_column('batch_generation_tasks', 'current_chapter_phase')
    op.drop_column('batch_generation_tasks', 'current_chapter_target_chars')
    op.drop_column('batch_generation_tasks', 'current_chapter_chars')
