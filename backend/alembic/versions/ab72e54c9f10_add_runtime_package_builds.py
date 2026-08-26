"""add runtime package builds

Revision ID: ab72e54c9f10
Revises: f2a8c1d4e907
Create Date: 2026-08-24 19:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ab72e54c9f10"
down_revision: Union[str, None] = "f2a8c1d4e907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_package_builds",
        sa.Column("build_number", sa.Integer(), nullable=False, comment="递增构建序号"),
        sa.Column("version", sa.String(length=60), nullable=False, comment="运行包版本"),
        sa.Column("target_environment", sa.String(length=30), nullable=False, comment="目标运行环境"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="构建状态"),
        sa.Column("artifact_path", sa.String(length=1000), nullable=True, comment="运行包本机绝对路径"),
        sa.Column("file_count", sa.Integer(), nullable=False, comment="运行包文件数量"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, comment="运行包字节大小"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, comment="构建开始时间"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="构建完成时间"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="构建失败原因"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("status IN ('building','succeeded','failed')", name=op.f("ck_runtime_package_builds_valid_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_package_builds")),
        sa.UniqueConstraint("build_number", name=op.f("uq_runtime_package_builds_build_number")),
        sa.UniqueConstraint("version", name=op.f("uq_runtime_package_builds_version")),
        comment="智矩仅代码运行包构建记录",
    )
    op.create_index("ix_runtime_package_builds_status_created", "runtime_package_builds", ["status", "created_at"], unique=False)
    comments = {
        "__table__": "智矩仅代码运行包构建记录",
        "id": "系统内部稳定主键",
        "build_number": "递增构建序号",
        "version": "运行包版本",
        "target_environment": "目标运行环境",
        "status": "构建状态",
        "artifact_path": "运行包本机绝对路径",
        "file_count": "运行包文件数量",
        "size_bytes": "运行包字节大小",
        "started_at": "构建开始时间",
        "completed_at": "构建完成时间",
        "error_message": "构建失败原因",
        "created_at": "创建时间",
        "updated_at": "最后更新时间",
    }
    values = ",".join(
        "(%s,%s,%s,NOW())" % (repr("runtime_package_builds"), repr(column), repr(comment))
        for column, comment in comments.items()
    )
    op.execute(sa.text("REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) VALUES " + values))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_comments WHERE table_name = 'runtime_package_builds'"))
    op.drop_index("ix_runtime_package_builds_status_created", table_name="runtime_package_builds")
    op.drop_table("runtime_package_builds")
