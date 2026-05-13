"""为 batch_generation_tasks 增加章节级实时进度字段

Revision ID: a8b9c0d1e2fd
Revises: f6a7b8c9d0ec
Create Date: 2026-05-13 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a8b9c0d1e2fd'
down_revision = 'f6a7b8c9d0ec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_generation_tasks') as batch_op:
        batch_op.add_column(sa.Column('current_chapter_chars', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('current_chapter_target_chars', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('current_chapter_phase', sa.String(length=20), nullable=False, server_default='waiting'))


def downgrade() -> None:
    with op.batch_alter_table('batch_generation_tasks') as batch_op:
        batch_op.drop_column('current_chapter_phase')
        batch_op.drop_column('current_chapter_target_chars')
        batch_op.drop_column('current_chapter_chars')
