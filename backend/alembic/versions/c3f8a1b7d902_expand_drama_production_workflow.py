"""expand drama production workflow

Revision ID: c3f8a1b7d902
Revises: 9c2d4e6f8a10
Create Date: 2026-08-28 14:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "c3f8a1b7d902"
down_revision = "9c2d4e6f8a10"
branch_labels = None
depends_on = None


NODE_STATUS_SQL = "('not_started','in_progress','completed','failed')"
OLD_NODE_COLUMNS = (
    "cloud_download_status",
    "parameter_normalization_status",
    "subtitle_extraction_status",
    "guishou_upload_status",
    "role_extraction_status",
    "production_completion_status",
)
NEW_NODE_COLUMNS = (
    "cloud_download_status",
    "parameter_normalization_status",
    "youtube_upload_status",
    "copyright_verification_status",
    "subtitle_extraction_status",
    "guishou_upload_status",
    "role_extraction_status",
    "tts_status",
    "production_completion_status",
)


def _status_check(columns: tuple[str, ...]) -> str:
    return " AND ".join(f"{column} IN {NODE_STATUS_SQL}" for column in columns)


def upgrade() -> None:
    op.drop_constraint(
        "ck_drama_production_states_valid_node_statuses",
        "drama_production_states",
        type_="check",
    )
    op.add_column(
        "drama_production_states",
        sa.Column("youtube_upload_status", sa.String(length=20), server_default="not_started", nullable=False, comment="上传YouTube状态"),
    )
    op.add_column(
        "drama_production_states",
        sa.Column("copyright_verification_status", sa.String(length=20), server_default="not_started", nullable=False, comment="版权验证状态"),
    )
    op.add_column(
        "drama_production_states",
        sa.Column("tts_status", sa.String(length=20), server_default="not_started", nullable=False, comment="TTS状态"),
    )
    op.add_column(
        "drama_production_states",
        sa.Column("is_production_excluded", sa.Boolean(), server_default=sa.false(), nullable=False, comment="是否不进行制作"),
    )
    op.execute(sa.text("""
        UPDATE drama_production_states
        SET youtube_upload_status = CASE
                WHEN subtitle_extraction_status <> 'not_started' THEN 'completed'
                WHEN parameter_normalization_status = 'completed' THEN 'in_progress'
                ELSE 'not_started'
            END,
            copyright_verification_status = CASE
                WHEN subtitle_extraction_status <> 'not_started' THEN 'completed'
                ELSE 'not_started'
            END,
            tts_status = CASE
                WHEN production_completion_status <> 'not_started' THEN 'completed'
                WHEN role_extraction_status = 'completed' THEN 'in_progress'
                ELSE 'not_started'
            END
    """))
    op.create_check_constraint(
        "ck_drama_production_states_valid_node_statuses",
        "drama_production_states",
        _status_check(NEW_NODE_COLUMNS),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_drama_production_states_valid_node_statuses",
        "drama_production_states",
        type_="check",
    )
    op.drop_column("drama_production_states", "is_production_excluded")
    op.drop_column("drama_production_states", "tts_status")
    op.drop_column("drama_production_states", "copyright_verification_status")
    op.drop_column("drama_production_states", "youtube_upload_status")
    op.create_check_constraint(
        "ck_drama_production_states_valid_node_statuses",
        "drama_production_states",
        _status_check(OLD_NODE_COLUMNS),
    )
