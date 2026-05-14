"""添加 projects.generation_settings 字段

Revision ID: b8c9d0e1f2ad
Revises: a7b8c9d0e1fc
Create Date: 2026-05-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b8c9d0e1f2ad'
down_revision = 'a7b8c9d0e1fc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column('generation_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('projects', 'generation_settings')
