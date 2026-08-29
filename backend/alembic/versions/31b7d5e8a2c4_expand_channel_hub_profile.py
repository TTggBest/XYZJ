"""expand channel hub profile

Revision ID: 31b7d5e8a2c4
Revises: 2f6c8a1d4b90
Create Date: 2026-08-29 15:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "31b7d5e8a2c4"
down_revision = "2f6c8a1d4b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("chinese_meaning", sa.String(length=255), nullable=True, comment="频道名中文含义"),
    )
    op.add_column(
        "channel_profiles",
        sa.Column("avatar_prompt", sa.Text(), nullable=True, comment="头像出图词"),
    )
    op.add_column(
        "channel_profiles",
        sa.Column("banner_prompt", sa.Text(), nullable=True, comment="横幅出图词"),
    )


def downgrade() -> None:
    op.drop_column("channel_profiles", "banner_prompt")
    op.drop_column("channel_profiles", "avatar_prompt")
    op.drop_column("channels", "chinese_meaning")
