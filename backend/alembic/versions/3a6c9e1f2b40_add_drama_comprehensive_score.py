"""add drama comprehensive score

Revision ID: 3a6c9e1f2b40
Revises: 8f2b7d5c0e31
Create Date: 2026-09-01 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "3a6c9e1f2b40"
down_revision = "8f2b7d5c0e31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dramas",
        sa.Column("comprehensive_score", sa.Numeric(precision=8, scale=2), nullable=True, comment="飞书剧库综合评分"),
    )


def downgrade() -> None:
    op.drop_column("dramas", "comprehensive_score")
