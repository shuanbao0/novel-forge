"""添加分级契约字段(outline.creative_brief / chapter.creative_brief)

Revision ID: e5f6a7b8c9da
Revises: d4e5f6a7b8c9
Create Date: 2026-05-11 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'e5f6a7b8c9da'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('outlines', sa.Column('creative_brief', JSONB, nullable=True, comment='卷级契约'))
    op.add_column('chapters', sa.Column('creative_brief', JSONB, nullable=True, comment='章级契约'))


def downgrade() -> None:
    op.drop_column('chapters', 'creative_brief')
    op.drop_column('outlines', 'creative_brief')
