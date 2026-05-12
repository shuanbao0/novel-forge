"""添加分级契约字段(outline.creative_brief / chapter.creative_brief)

Revision ID: e6f7a8b9cadb
Revises: d5e6f7a8b9ca
Create Date: 2026-05-11 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9cadb'
down_revision = 'd5e6f7a8b9ca'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('outlines') as batch_op:
        batch_op.add_column(sa.Column('creative_brief', sa.JSON(), nullable=True))
    with op.batch_alter_table('chapters') as batch_op:
        batch_op.add_column(sa.Column('creative_brief', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('chapters') as batch_op:
        batch_op.drop_column('creative_brief')
    with op.batch_alter_table('outlines') as batch_op:
        batch_op.drop_column('creative_brief')
