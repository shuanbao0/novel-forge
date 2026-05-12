"""添加 projects.style_patterns 字段

Revision ID: f5a6b7c8d9eb
Revises: e5f6a7b8c9da
Create Date: 2026-05-11 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'f5a6b7c8d9eb'
down_revision = 'e5f6a7b8c9da'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('style_patterns', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'style_patterns')
