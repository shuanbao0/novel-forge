"""添加创作契约字段

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-11 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column(
            'creative_contract', JSONB, nullable=True,
            comment='创作契约:全局约束/反模式/读者承诺',
        ),
    )


def downgrade() -> None:
    op.drop_column('projects', 'creative_contract')
