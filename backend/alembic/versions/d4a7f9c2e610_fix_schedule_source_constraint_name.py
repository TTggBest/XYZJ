"""fix schedule source constraint name

Revision ID: d4a7f9c2e610
Revises: b2d6e8f1a430
Create Date: 2026-08-29 02:35:00
"""

from alembic import op


revision = "d4a7f9c2e610"
down_revision = "b2d6e8f1a430"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_channel_schedule_entries_ck_channel_schedule_entries__f7be"),
        "channel_schedule_entries",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_channel_schedule_entries_valid_source_type"),
        "channel_schedule_entries",
        "source_type IN ('manual','feishu','system')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_channel_schedule_entries_valid_source_type"),
        "channel_schedule_entries",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_channel_schedule_entries_ck_channel_schedule_entries__f7be"),
        "channel_schedule_entries",
        "source_type IN ('manual','feishu','system')",
    )
