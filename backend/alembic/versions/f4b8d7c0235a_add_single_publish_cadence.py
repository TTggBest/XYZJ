"""add single publish cadence

Revision ID: f4b8d7c0235a
Revises: e3a7c6b9124f
Create Date: 2026-08-25 18:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "f4b8d7c0235a"
down_revision = "e3a7c6b9124f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE publish_cadence_template_slots
        DROP CHECK ck_publish_cadence_template_slots_valid_daily_publish_count
    """))
    op.execute(sa.text("""
        ALTER TABLE publish_cadence_template_slots
        ADD CONSTRAINT ck_publish_cadence_template_slots_valid_daily_publish_count
        CHECK (daily_publish_count BETWEEN 1 AND 5)
    """))
    op.execute(sa.text("""
        INSERT INTO publish_cadence_template_slots
            (id, daily_publish_count, slot_number, slot_type, local_video_time,
             engagement_offset_minutes, created_at, updated_at)
        VALUES (UUID(), 1, 1, 'main', '18:00:00', 120, NOW(), NOW())
    """))
    op.execute(sa.text("""
        ALTER TABLE publish_cadence_template_slots
        COMMENT = '每日1至5更的全局视频与二次触达时间模板'
    """))
    op.execute(sa.text("""
        REPLACE INTO schema_comments
            (table_name, column_name, chinese_comment, updated_at)
        VALUES
            ('publish_cadence_template_slots', '__table__',
             '每日1至5更的全局视频与二次触达时间模板', NOW())
    """))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM publish_cadence_template_slots WHERE daily_publish_count = 1"
    ))
    op.execute(sa.text("""
        ALTER TABLE publish_cadence_template_slots
        DROP CHECK ck_publish_cadence_template_slots_valid_daily_publish_count
    """))
    op.execute(sa.text("""
        ALTER TABLE publish_cadence_template_slots
        ADD CONSTRAINT ck_publish_cadence_template_slots_valid_daily_publish_count
        CHECK (daily_publish_count BETWEEN 2 AND 5)
    """))
    op.execute(sa.text("""
        ALTER TABLE publish_cadence_template_slots
        COMMENT = '每日2至5更的全局视频与二次触达时间模板'
    """))
    op.execute(sa.text("""
        REPLACE INTO schema_comments
            (table_name, column_name, chinese_comment, updated_at)
        VALUES
            ('publish_cadence_template_slots', '__table__',
             '每日2至5更的全局视频与二次触达时间模板', NOW())
    """))
