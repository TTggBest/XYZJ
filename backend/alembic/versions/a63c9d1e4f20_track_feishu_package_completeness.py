"""track feishu package completeness

Revision ID: a63c9d1e4f20
Revises: f4b8d7c0235a
Create Date: 2026-08-26 17:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "a63c9d1e4f20"
down_revision = "f4b8d7c0235a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operation_packages",
        sa.Column("source_complete", sa.Boolean(), server_default="1", nullable=False, comment="飞书源数据是否完整"),
    )
    op.add_column(
        "operation_packages",
        sa.Column("source_incomplete_reason", sa.Text(), nullable=True, comment="飞书源数据不完整原因"),
    )
    op.execute(sa.text("""
        REPLACE INTO schema_comments
            (table_name, column_name, chinese_comment, updated_at)
        VALUES
            ('operation_packages', 'source_complete', '飞书源数据是否完整', NOW()),
            ('operation_packages', 'source_incomplete_reason', '飞书源数据不完整原因', NOW())
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        DELETE FROM schema_comments
        WHERE table_name = 'operation_packages'
          AND column_name IN ('source_complete', 'source_incomplete_reason')
    """))
    op.drop_column("operation_packages", "source_incomplete_reason")
    op.drop_column("operation_packages", "source_complete")
