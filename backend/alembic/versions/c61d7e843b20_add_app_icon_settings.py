"""add app icon settings

Revision ID: c61d7e843b20
Revises: ab72e54c9f10
Create Date: 2026-08-24 20:15:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c61d7e843b20"
down_revision: Union[str, None] = "ab72e54c9f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_icon_settings",
        sa.Column("id", sa.String(length=36), nullable=False, comment="固定设置主键"),
        sa.Column("source_type", sa.String(length=20), nullable=False, comment="图标来源类型"),
        sa.Column("source_path", sa.String(length=1000), nullable=False, comment="当前图标源文件路径"),
        sa.Column("original_filename", sa.String(length=255), nullable=True, comment="上传时原始文件名"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, comment="最近应用时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("source_type IN ('default','custom')", name=op.f("ck_app_icon_settings_valid_source_type")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_icon_settings")),
        comment="智矩当前应用图标设置",
    )
    op.execute(sa.text("INSERT INTO app_icon_settings (id,source_type,source_path,original_filename,applied_at,created_at,updated_at) VALUES ('current-app-icon','default','assets/app-icon-default.png','app-icon-default.png',NOW(),NOW(),NOW())"))
    comments = {
        "__table__": "智矩当前应用图标设置",
        "id": "固定设置主键",
        "source_type": "图标来源类型",
        "source_path": "当前图标源文件路径",
        "original_filename": "上传时原始文件名",
        "applied_at": "最近应用时间",
        "created_at": "创建时间",
        "updated_at": "最后更新时间",
    }
    values = ",".join("(%s,%s,%s,NOW())" % (repr("app_icon_settings"), repr(column), repr(comment)) for column, comment in comments.items())
    op.execute(sa.text("REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) VALUES " + values))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_comments WHERE table_name = 'app_icon_settings'"))
    op.drop_table("app_icon_settings")
