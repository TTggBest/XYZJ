"""add package output copy progress

Revision ID: f2a8c1d4e907
Revises: d4f2a73c9b11
Create Date: 2026-08-24 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "f2a8c1d4e907"
down_revision: Union[str, None] = "d4f2a73c9b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "package_output_copy_states",
        sa.Column("package_id", sa.String(length=36), nullable=False, comment="运营包ID"),
        sa.Column("output_type", sa.String(length=30), nullable=False, comment="被复制的产物类型"),
        sa.Column("output_id", sa.String(length=36), nullable=False, comment="被复制的当前产物ID"),
        sa.Column("copied_at", mysql.DATETIME(fsp=6), nullable=False, comment="最近复制成功时间"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint(
            "output_type IN ('title','cover','description','community_text','community_image')",
            name=op.f("ck_package_output_copy_states_valid_output_type"),
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["operation_packages.id"],
            name=op.f("fk_package_output_copy_states_package_id_operation_packages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package_output_copy_states")),
        sa.UniqueConstraint("package_id", "output_type", "output_id", name="uq_package_output_copy_states_target"),
        comment="运营包当前产物的人工复制进度",
    )
    op.create_index(
        "ix_package_output_copy_states_package_time",
        "package_output_copy_states",
        ["package_id", "copied_at"],
        unique=False,
    )
    comments = {
        "__table__": "运营包当前产物的人工复制进度",
        "id": "系统内部稳定主键",
        "package_id": "运营包ID",
        "output_type": "被复制的产物类型",
        "output_id": "被复制的当前产物ID",
        "copied_at": "最近复制成功时间",
        "created_at": "创建时间",
        "updated_at": "最后更新时间",
    }
    values = ",".join(
        "(%s,%s,%s,NOW())" % (repr("package_output_copy_states"), repr(column), repr(comment))
        for column, comment in comments.items()
    )
    op.execute(sa.text("REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) VALUES " + values))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_comments WHERE table_name = 'package_output_copy_states'"))
    op.drop_index("ix_package_output_copy_states_package_time", table_name="package_output_copy_states")
    op.drop_table("package_output_copy_states")
