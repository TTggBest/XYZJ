"""add channel schedule sync type

Revision ID: b2d6e8f1a430
Revises: e7b9c4a2d615
Create Date: 2026-08-29 12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "b2d6e8f1a430"
down_revision = "e7b9c4a2d615"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages','channels','dramas','drama_languages','channel_schedules'))
    """))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages','channels','dramas','drama_languages'))
    """))
