"""add demo data batches

Revision ID: d4f2a73c9b11
Revises: 8448b607e05f
Create Date: 2026-08-24 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f2a73c9b11"
down_revision: Union[str, None] = "8448b607e05f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demo_data_batches",
        sa.Column("batch_code", sa.String(length=100), nullable=False, comment="演示批次稳定代码"),
        sa.Column("source_label", sa.String(length=255), nullable=False, comment="演示数据来源说明"),
        sa.Column("row_count", sa.Integer(), nullable=False, comment="导入的业务行数"),
        sa.Column("start_date", sa.Date(), nullable=False, comment="演示任务起始日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="演示任务结束日期"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="批次状态"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, comment="一键删除完成时间"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("status IN ('active','deleted')", name=op.f("ck_demo_data_batches_valid_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demo_data_batches")),
        sa.UniqueConstraint("batch_code", name=op.f("uq_demo_data_batches_batch_code")),
        comment="可整体删除的本机演示数据批次",
    )
    op.create_table(
        "demo_data_entities",
        sa.Column("batch_id", sa.String(length=36), nullable=False, comment="所属演示批次ID"),
        sa.Column("entity_type", sa.String(length=80), nullable=False, comment="实体类型"),
        sa.Column("entity_id", sa.String(length=36), nullable=False, comment="实体内部ID"),
        sa.Column("owned", sa.Boolean(), server_default="1", nullable=False, comment="删除批次时是否删除该实体"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.ForeignKeyConstraint(["batch_id"], ["demo_data_batches.id"], name=op.f("fk_demo_data_entities_batch_id_demo_data_batches"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demo_data_entities")),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_demo_data_entities_entity"),
        comment="演示批次实际创建并拥有的数据库实体",
    )
    op.create_index("ix_demo_data_entities_batch_type", "demo_data_entities", ["batch_id", "entity_type"], unique=False)
    comments = {
        "demo_data_batches": {
            "__table__": "可整体删除的本机演示数据批次", "id": "系统内部稳定主键", "batch_code": "演示批次稳定代码",
            "source_label": "演示数据来源说明", "row_count": "导入的业务行数", "start_date": "演示任务起始日期",
            "end_date": "演示任务结束日期", "status": "批次状态", "deleted_at": "一键删除完成时间",
            "created_at": "创建时间", "updated_at": "最后更新时间",
        },
        "demo_data_entities": {
            "__table__": "演示批次实际创建并拥有的数据库实体", "id": "系统内部稳定主键", "batch_id": "所属演示批次ID",
            "entity_type": "实体类型", "entity_id": "实体内部ID", "owned": "删除批次时是否删除该实体",
            "created_at": "创建时间", "updated_at": "最后更新时间",
        },
    }
    values = ",".join(
        "(%s,%s,%s,NOW())" % (repr(table), repr(column), repr(comment))
        for table, columns in comments.items() for column, comment in columns.items()
    )
    op.execute(sa.text("REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) VALUES " + values))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_comments WHERE table_name IN ('demo_data_entities','demo_data_batches')"))
    op.drop_index("ix_demo_data_entities_batch_type", table_name="demo_data_entities")
    op.drop_table("demo_data_entities")
    op.drop_table("demo_data_batches")
