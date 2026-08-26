"""add feishu batches and drama numbers

Revision ID: 7b41c92e6f30
Revises: e84f3c91a72d
Create Date: 2026-08-24 23:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "7b41c92e6f30"
down_revision: Union[str, None] = "e84f3c91a72d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _comments(table_name: str, comments: dict[str, str]) -> None:
    values = ",".join(
        "(%s,%s,%s,NOW())" % (repr(table_name), repr(column), repr(comment))
        for column, comment in comments.items()
    )
    op.execute(sa.text(
        "REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) VALUES " + values
    ))


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE dramas ADD COLUMN drama_number BIGINT NOT NULL AUTO_INCREMENT UNIQUE COMMENT '剧库自增编号' AFTER id"
    ))
    op.create_table(
        "production_batches",
        sa.Column("batch_number", sa.String(length=80), nullable=False, comment="对外批次号"),
        sa.Column("production_date", sa.Date(), nullable=False, comment="批次生产日期"),
        sa.Column("source", sa.String(length=20), nullable=False, comment="批次来源"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="批次状态"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("source IN ('native','feishu')", name=op.f("ck_production_batches_valid_source")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_batches")),
        sa.UniqueConstraint("batch_number", name=op.f("uq_production_batches_batch_number")),
        comment="生产任务的稳定批次",
    )
    op.create_index("ix_production_batches_date_source", "production_batches", ["production_date", "source"])
    op.create_table(
        "feishu_sync_runs",
        sa.Column("sync_type", sa.String(length=30), nullable=False, comment="同步数据类型"),
        sa.Column("sheet_id", sa.String(length=40), nullable=False, comment="飞书工作表ID"),
        sa.Column("environment", sa.String(length=30), nullable=False, comment="执行环境"),
        sa.Column("device_key", sa.String(length=160), nullable=True, comment="执行设备标识"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="同步状态"),
        sa.Column("rows_read", sa.Integer(), server_default="0", nullable=False, comment="读取行数"),
        sa.Column("rows_inserted", sa.Integer(), server_default="0", nullable=False, comment="新增行数"),
        sa.Column("rows_updated", sa.Integer(), server_default="0", nullable=False, comment="更新行数"),
        sa.Column("rows_skipped", sa.Integer(), server_default="0", nullable=False, comment="跳过行数"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="同步失败原因"),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=False, comment="开始时间"),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True, comment="完成时间"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("sync_type IN ('work_orders','operation_packages')", name=op.f("ck_feishu_sync_runs_valid_sync_type")),
        sa.CheckConstraint("status IN ('running','completed','failed')", name=op.f("ck_feishu_sync_runs_valid_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feishu_sync_runs")),
        comment="飞书工单与运营包同步执行记录",
    )
    op.create_index("ix_feishu_sync_runs_type_time", "feishu_sync_runs", ["sync_type", "started_at"])

    for table in ("operation_tasks", "work_orders", "operation_packages"):
        op.add_column(table, sa.Column("batch_id", sa.String(length=36), nullable=True, comment="生产批次ID"))
        op.create_foreign_key(op.f(f"fk_{table}_batch_id_production_batches"), table, "production_batches", ["batch_id"], ["id"], ondelete="RESTRICT")
        op.create_index(op.f(f"ix_{table}_batch_id"), table, ["batch_id"])
    op.add_column("operation_tasks", sa.Column("source_video_id", sa.String(length=32), nullable=True, comment="来源视频Video ID"))
    op.add_column("operation_tasks", sa.Column("source_video_url", sa.String(length=1000), nullable=True, comment="来源剧目视频地址"))
    op.create_index("ix_operation_tasks_source_video_id", "operation_tasks", ["source_video_id"])

    _comments("dramas", {"drama_number": "剧库自增编号"})
    _comments("production_batches", {
        "__table__": "生产任务的稳定批次", "id": "系统内部稳定主键", "batch_number": "对外批次号",
        "production_date": "批次生产日期", "source": "批次来源", "status": "批次状态", "created_at": "创建时间", "updated_at": "最后更新时间",
    })
    _comments("feishu_sync_runs", {
        "__table__": "飞书工单与运营包同步执行记录", "id": "系统内部稳定主键", "sync_type": "同步数据类型", "sheet_id": "飞书工作表ID",
        "environment": "执行环境", "device_key": "执行设备标识", "status": "同步状态", "rows_read": "读取行数", "rows_inserted": "新增行数",
        "rows_updated": "更新行数", "rows_skipped": "跳过行数", "error_message": "同步失败原因", "started_at": "开始时间", "completed_at": "完成时间",
        "created_at": "创建时间", "updated_at": "最后更新时间",
    })
    for table in ("operation_tasks", "work_orders", "operation_packages"):
        _comments(table, {"batch_id": "生产批次ID"})
    _comments("operation_tasks", {"source_video_id": "来源视频Video ID", "source_video_url": "来源剧目视频地址"})


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_comments WHERE table_name IN ('production_batches','feishu_sync_runs') OR (table_name='dramas' AND column_name='drama_number') OR (table_name IN ('operation_tasks','work_orders','operation_packages') AND column_name IN ('batch_id','source_video_id','source_video_url'))"))
    op.drop_index("ix_operation_tasks_source_video_id", table_name="operation_tasks")
    op.drop_column("operation_tasks", "source_video_url")
    op.drop_column("operation_tasks", "source_video_id")
    for table in ("operation_packages", "work_orders", "operation_tasks"):
        op.drop_index(op.f(f"ix_{table}_batch_id"), table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_batch_id_production_batches"), table, type_="foreignkey")
        op.drop_column(table, "batch_id")
    op.drop_index("ix_feishu_sync_runs_type_time", table_name="feishu_sync_runs")
    op.drop_table("feishu_sync_runs")
    op.drop_index("ix_production_batches_date_source", table_name="production_batches")
    op.drop_table("production_batches")
    op.drop_column("dramas", "drama_number")
