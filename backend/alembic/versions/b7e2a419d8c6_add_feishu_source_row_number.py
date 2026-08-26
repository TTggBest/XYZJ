"""add Feishu source row number

Revision ID: b7e2a419d8c6
Revises: 7b41c92e6f30
Create Date: 2026-08-24 20:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e2a419d8c6"
down_revision = "7b41c92e6f30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operation_tasks",
        sa.Column("source_row_number", sa.Integer(), nullable=True, comment="来源飞书表格原始行号"),
    )
    op.create_index(
        "ix_operation_tasks_source_row_number",
        "operation_tasks",
        ["source_row_number"],
        unique=False,
    )
    op.execute(sa.text(
        "REPLACE INTO schema_comments "
        "(table_name,column_name,chinese_comment,updated_at) VALUES "
        "('operation_tasks','source_row_number','来源飞书表格原始行号',CURRENT_TIMESTAMP(6))"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM schema_comments WHERE table_name='operation_tasks' AND column_name='source_row_number'"
    ))
    op.drop_index("ix_operation_tasks_source_row_number", table_name="operation_tasks")
    op.drop_column("operation_tasks", "source_row_number")
