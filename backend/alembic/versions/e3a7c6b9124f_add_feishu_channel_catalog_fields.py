"""add Feishu channel catalog fields

Revision ID: e3a7c6b9124f
Revises: d92c4a7e51b3
Create Date: 2026-08-25 16:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "e3a7c6b9124f"
down_revision = "d92c4a7e51b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("channels", "channel_profiles")
    }
    additions = {
        "channels": [
            sa.Column("youtube_channel_url", sa.String(length=1000), nullable=True, comment="YouTube频道主页地址"),
            sa.Column("channel_type", sa.String(length=120), nullable=True, comment="频道内容类型"),
            sa.Column("drama_type", sa.String(length=60), nullable=True, comment="短剧受众类型"),
            sa.Column("application_success_date", sa.Date(), nullable=True, comment="频道申请成功日期"),
            sa.Column("display_order", sa.SmallInteger(), nullable=True, comment="频道总表展示序号"),
        ],
        "channel_profiles": [
            sa.Column("popup_scheme", sa.String(length=120), nullable=True, comment="标题弹框方案"),
            sa.Column("title_template", sa.Text(), nullable=True, comment="频道标题模板"),
            sa.Column("fixed_symbol", sa.String(length=120), nullable=True, comment="标题固定符号"),
        ],
    }
    for table, columns in additions.items():
        for column in columns:
            if column.name not in existing[table]:
                op.add_column(table, column)

    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages','channels'))
    """))
    op.execute(sa.text("""
        REPLACE INTO schema_comments (table_name, column_name, chinese_comment, updated_at)
        SELECT table_name, column_name, column_comment, NOW()
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name IN ('channels', 'channel_profiles')
          AND column_comment <> ''
    """))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE feishu_sync_runs DROP CHECK ck_feishu_sync_runs_valid_sync_type"))
    op.execute(sa.text("""
        ALTER TABLE feishu_sync_runs
        ADD CONSTRAINT ck_feishu_sync_runs_valid_sync_type
        CHECK (sync_type IN ('work_orders','operation_packages'))
    """))
    op.execute(sa.text("""
        DELETE FROM schema_comments
        WHERE (table_name = 'channels' AND column_name IN (
            'youtube_channel_url', 'channel_type', 'drama_type',
            'application_success_date', 'display_order'
        )) OR (table_name = 'channel_profiles' AND column_name IN (
            'popup_scheme', 'title_template', 'fixed_symbol'
        ))
    """))
    op.drop_column("channel_profiles", "fixed_symbol")
    op.drop_column("channel_profiles", "title_template")
    op.drop_column("channel_profiles", "popup_scheme")
    op.drop_column("channels", "display_order")
    op.drop_column("channels", "application_success_date")
    op.drop_column("channels", "drama_type")
    op.drop_column("channels", "channel_type")
    op.drop_column("channels", "youtube_channel_url")
