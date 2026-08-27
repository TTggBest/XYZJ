"""add drama production progress

Revision ID: 9c2d4e6f8a10
Revises: 5db7a3c821e4
Create Date: 2026-08-28 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "9c2d4e6f8a10"
down_revision = "5db7a3c821e4"
branch_labels = None
depends_on = None


NODE_STATUS_SQL = "('not_started','in_progress','completed','failed')"


def upgrade() -> None:
    op.add_column("languages", sa.Column("priority_tier", sa.String(length=1), nullable=True, comment="语言制作优先级"))
    op.create_check_constraint(
        "ck_languages_valid_priority_tier",
        "languages",
        "priority_tier IS NULL OR priority_tier IN ('S','A','B','C')",
    )
    op.add_column(
        "drama_translations",
        sa.Column("source_type", sa.String(length=20), server_default="manual", nullable=False, comment="语言覆盖来源"),
    )
    op.add_column(
        "drama_translations",
        sa.Column("source_synced_at", sa.DateTime(), nullable=True, comment="最后一次飞书同步时间"),
    )
    op.create_check_constraint(
        "ck_drama_translations_valid_source_type",
        "drama_translations",
        "source_type IN ('manual','feishu')",
    )
    op.create_table(
        "drama_production_states",
        sa.Column("drama_id", sa.String(length=36), nullable=False, comment="剧目内部ID"),
        sa.Column("cloud_download_status", sa.String(length=20), server_default="not_started", nullable=False, comment="网盘下载状态"),
        sa.Column("parameter_normalization_status", sa.String(length=20), server_default="not_started", nullable=False, comment="统一参数状态"),
        sa.Column("subtitle_extraction_status", sa.String(length=20), server_default="not_started", nullable=False, comment="字幕提取状态"),
        sa.Column("guishou_upload_status", sa.String(length=20), server_default="not_started", nullable=False, comment="鬼手上传状态"),
        sa.Column("role_extraction_status", sa.String(length=20), server_default="not_started", nullable=False, comment="角色提取状态"),
        sa.Column("production_completion_status", sa.String(length=20), server_default="not_started", nullable=False, comment="制作完成状态"),
        sa.Column("episode_count", sa.Integer(), nullable=True, comment="剧集数"),
        sa.Column("total_duration_seconds", sa.Integer(), nullable=True, comment="剧集合集时长秒数"),
        sa.Column("source_type", sa.String(length=20), server_default="manual", nullable=False, comment="进度来源"),
        sa.Column("source_external_id", sa.String(length=120), nullable=True, comment="智核剧目ID"),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True, comment="智核数据更新时间"),
        sa.Column("source_synced_at", sa.DateTime(), nullable=True, comment="最近同步时间"),
        sa.Column("last_error", sa.Text(), nullable=True, comment="最近失败原因"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint(
            " AND ".join(
                f"{column} IN {NODE_STATUS_SQL}"
                for column in (
                    "cloud_download_status",
                    "parameter_normalization_status",
                    "subtitle_extraction_status",
                    "guishou_upload_status",
                    "role_extraction_status",
                    "production_completion_status",
                )
            ),
            name="ck_drama_production_states_valid_node_statuses",
        ),
        sa.CheckConstraint("source_type IN ('manual','zhihe')", name="ck_drama_production_states_valid_source_type"),
        sa.CheckConstraint("episode_count IS NULL OR episode_count >= 0", name="ck_drama_production_states_episode_count_nonnegative"),
        sa.CheckConstraint("total_duration_seconds IS NULL OR total_duration_seconds >= 0", name="ck_drama_production_states_duration_nonnegative"),
        sa.ForeignKeyConstraint(["drama_id"], ["dramas.id"], name="fk_drama_production_states_drama_id_dramas", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_drama_production_states"),
        sa.UniqueConstraint("drama_id", name="uq_drama_production_states_drama"),
        comment="每部剧唯一一套制剧进度",
    )
    op.create_index(
        "ix_drama_production_states_source",
        "drama_production_states",
        ["source_type", "source_updated_at"],
        unique=False,
    )
    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages','channels','dramas','drama_languages'))
    """))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages','channels','dramas'))
    """))
    op.drop_index("ix_drama_production_states_source", table_name="drama_production_states")
    op.drop_table("drama_production_states")
    op.drop_constraint("ck_drama_translations_valid_source_type", "drama_translations", type_="check")
    op.drop_column("drama_translations", "source_synced_at")
    op.drop_column("drama_translations", "source_type")
    op.drop_constraint("ck_languages_valid_priority_tier", "languages", type_="check")
    op.drop_column("languages", "priority_tier")
