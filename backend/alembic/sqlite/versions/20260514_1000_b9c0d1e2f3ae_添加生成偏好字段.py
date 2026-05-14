"""添加 projects.generation_settings 字段

Revision ID: b9c0d1e2f3ae
Revises: a8b9c0d1e2fd
Create Date: 2026-05-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b9c0d1e2f3ae'
down_revision = 'a8b9c0d1e2fd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('generation_settings', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('generation_settings')
