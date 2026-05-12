"""添加 projects.style_patterns 字段

Revision ID: f6a7b8c9d0ec
Revises: e6f7a8b9cadb
Create Date: 2026-05-11 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0ec'
down_revision = 'e6f7a8b9cadb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('style_patterns', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('style_patterns')
