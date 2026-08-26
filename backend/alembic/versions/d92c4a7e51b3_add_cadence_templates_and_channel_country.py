"""add cadence templates and channel country

Revision ID: d92c4a7e51b3
Revises: b7e2a419d8c6
Create Date: 2026-08-25 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "d92c4a7e51b3"
down_revision = "b7e2a419d8c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("country_code", sa.String(length=2), nullable=True, comment="频道目标国家或地区代码"),
    )
    op.add_column(
        "channels",
        sa.Column("country_name_zh", sa.String(length=120), nullable=True, comment="频道目标国家或地区中文名称"),
    )
    op.create_table(
        "publish_cadence_template_slots",
        sa.Column("daily_publish_count", sa.SmallInteger(), nullable=False, comment="模板每日更新次数"),
        sa.Column("slot_number", sa.SmallInteger(), nullable=False, comment="模板内按时间排序的档位序号"),
        sa.Column("slot_type", sa.String(length=20), nullable=False, comment="主档或辅档"),
        sa.Column("local_video_time", sa.Time(), nullable=False, comment="目标国家当地视频发布时间"),
        sa.Column(
            "engagement_offset_minutes",
            sa.Integer(),
            server_default="120",
            nullable=False,
            comment="社区或Shorts相对视频延迟分钟数",
        ),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("daily_publish_count BETWEEN 2 AND 5", name=op.f("ck_publish_cadence_template_slots_valid_daily_publish_count")),
        sa.CheckConstraint("slot_number >= 1", name=op.f("ck_publish_cadence_template_slots_slot_number_positive")),
        sa.CheckConstraint("slot_type IN ('main','aux')", name=op.f("ck_publish_cadence_template_slots_valid_slot_type")),
        sa.CheckConstraint("engagement_offset_minutes >= 0", name=op.f("ck_publish_cadence_template_slots_engagement_offset_nonnegative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_cadence_template_slots")),
        sa.UniqueConstraint("daily_publish_count", "slot_number", name="uq_cadence_template_slots_count_number"),
        comment="每日2至5更的全局视频与二次触达时间模板",
    )
    op.create_index(
        "ix_cadence_template_slots_count_type",
        "publish_cadence_template_slots",
        ["daily_publish_count", "slot_type", "slot_number"],
    )
    op.execute(sa.text("""
        INSERT INTO publish_cadence_template_slots
            (id, daily_publish_count, slot_number, slot_type, local_video_time, engagement_offset_minutes, created_at, updated_at)
        VALUES
            (UUID(), 2, 1, 'aux',  '10:00:00', 120, NOW(), NOW()),
            (UUID(), 2, 2, 'main', '18:00:00', 120, NOW(), NOW()),
            (UUID(), 3, 1, 'aux',  '10:00:00', 120, NOW(), NOW()),
            (UUID(), 3, 2, 'aux',  '14:00:00', 120, NOW(), NOW()),
            (UUID(), 3, 3, 'main', '18:00:00', 120, NOW(), NOW()),
            (UUID(), 4, 1, 'aux',  '10:00:00', 120, NOW(), NOW()),
            (UUID(), 4, 2, 'aux',  '14:00:00', 120, NOW(), NOW()),
            (UUID(), 4, 3, 'main', '18:00:00', 120, NOW(), NOW()),
            (UUID(), 4, 4, 'aux',  '21:00:00', 120, NOW(), NOW()),
            (UUID(), 5, 1, 'aux',  '06:00:00', 120, NOW(), NOW()),
            (UUID(), 5, 2, 'aux',  '10:00:00', 120, NOW(), NOW()),
            (UUID(), 5, 3, 'aux',  '14:00:00', 120, NOW(), NOW()),
            (UUID(), 5, 4, 'main', '18:00:00', 120, NOW(), NOW()),
            (UUID(), 5, 5, 'aux',  '21:00:00', 120, NOW(), NOW())
    """))
    op.execute(sa.text("""
        REPLACE INTO schema_comments (table_name, column_name, chinese_comment, updated_at)
        SELECT table_name, column_name, column_comment, NOW()
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name IN ('channels', 'publish_cadence_template_slots')
          AND column_comment <> ''
        UNION ALL
        SELECT table_name, '__table__', table_comment, NOW()
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = 'publish_cadence_template_slots'
          AND table_comment <> ''
    """))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM schema_comments WHERE "
        "table_name='publish_cadence_template_slots' OR "
        "(table_name='channels' AND column_name IN ('country_code','country_name_zh'))"
    ))
    op.drop_index("ix_cadence_template_slots_count_type", table_name="publish_cadence_template_slots")
    op.drop_table("publish_cadence_template_slots")
    op.drop_column("channels", "country_name_zh")
    op.drop_column("channels", "country_code")
