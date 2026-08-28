"""add drama library source fields

Revision ID: 5db7a3c821e4
Revises: b14c7e2a90d3
Create Date: 2026-08-27 15:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "5db7a3c821e4"
down_revision = "b14c7e2a90d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dramas", sa.Column("batch_name", sa.String(length=120), nullable=True, comment="来源批次"))
    op.add_column(
        "dramas",
        sa.Column("source_type", sa.String(length=20), server_default="manual", nullable=False, comment="剧目来源"),
    )
    op.add_column("dramas", sa.Column("source_sheet_id", sa.String(length=40), nullable=True, comment="来源飞书工作表ID"))
    op.add_column("dramas", sa.Column("source_row_number", sa.Integer(), nullable=True, comment="来源飞书原始行号"))
    op.add_column("dramas", sa.Column("source_synced_at", sa.DateTime(), nullable=True, comment="最后一次飞书同步时间"))
    op.create_check_constraint(
        "ck_dramas_valid_source_type",
        "dramas",
        "source_type IN ('manual','feishu')",
    )
    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages','channels','dramas'))
    """))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages','channels'))
    """))
    op.drop_constraint("ck_dramas_valid_source_type", "dramas", type_="check")
    op.drop_column("dramas", "source_synced_at")
    op.drop_column("dramas", "source_row_number")
    op.drop_column("dramas", "source_sheet_id")
    op.drop_column("dramas", "source_type")
    op.drop_column("dramas", "batch_name")
