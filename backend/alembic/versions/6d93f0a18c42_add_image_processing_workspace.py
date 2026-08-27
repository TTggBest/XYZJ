"""add image processing workspace

Revision ID: 6d93f0a18c42
Revises: a63c9d1e4f20
Create Date: 2026-08-26 21:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "6d93f0a18c42"
down_revision = "a63c9d1e4f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_workspace_settings",
        sa.Column("id", sa.String(36), primary_key=True, comment="固定设置主键"),
        sa.Column("root_path", sa.String(1000), nullable=False, comment="共享根目录下的相对路径或本机绝对路径"),
        sa.Column("persistent_dir_name", sa.String(120), nullable=False, server_default="系统素材", comment="不可随产物清理的必备素材目录名"),
        sa.Column("output_dir_name", sa.String(120), nullable=False, server_default="用户产物", comment="可清理的用户产物目录名"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        comment="图片生产共享根目录设置",
    )
    op.create_table(
        "channel_logo_profiles",
        sa.Column("id", sa.String(36), primary_key=True, comment="内部稳定ID"),
        sa.Column("channel_id", sa.String(36), nullable=False, comment="频道内部ID"),
        sa.Column("status", sa.String(20), nullable=False, comment="校准状态"),
        sa.Column("left_logo_path", sa.String(1000), nullable=False, comment="左Logo相对图片根目录路径"),
        sa.Column("right_logo_path", sa.String(1000), nullable=False, comment="右Logo相对图片根目录路径"),
        sa.Column("template_path", sa.String(1000), nullable=False, comment="校准模板相对图片根目录路径"),
        sa.Column("config_path", sa.String(1000), nullable=False, comment="自动生成的Logo配置相对路径"),
        sa.Column("canvas_width", sa.Integer(), nullable=False, comment="模板画布宽度"),
        sa.Column("canvas_height", sa.Integer(), nullable=False, comment="模板画布高度"),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), nullable=False, comment="最近自动校准时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("status IN ('calibrated','failed')", name="ck_channel_logo_profiles_valid_status"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("channel_id", name="uq_channel_logo_profiles_channel_id"),
        comment="频道左右Logo与模板自动校准配置",
    )
    op.create_table(
        "image_processing_runs",
        sa.Column("id", sa.String(36), primary_key=True, comment="内部稳定ID"),
        sa.Column("batch_id", sa.String(36), nullable=False, comment="生产批次ID"),
        sa.Column("status", sa.String(30), nullable=False, comment="处理状态"),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0", comment="导入图片数"),
        sa.Column("matched_files", sa.Integer(), nullable=False, server_default="0", comment="成功分类图片数"),
        sa.Column("unmatched_files", sa.Integer(), nullable=False, server_default="0", comment="未匹配图片数"),
        sa.Column("generated_files", sa.Integer(), nullable=False, server_default="0", comment="已生成Logo成品数"),
        sa.Column("manifest_path", sa.String(1000), nullable=True, comment="处理报告相对图片根目录路径"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="处理失败原因"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="最近处理完成时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("status IN ('processing','classified','partially_classified','logo_ready','partially_generated','failed')", name="ck_image_processing_runs_valid_status"),
        sa.ForeignKeyConstraint(["batch_id"], ["production_batches.id"], ondelete="RESTRICT"),
        comment="批次图片分类与Logo生成运行记录",
    )
    op.create_index("ix_image_processing_runs_batch_created", "image_processing_runs", ["batch_id", "created_at"])
    op.create_table(
        "image_processing_items",
        sa.Column("id", sa.String(36), primary_key=True, comment="内部稳定ID"),
        sa.Column("run_id", sa.String(36), nullable=False, comment="图片处理运行ID"),
        sa.Column("original_filename", sa.String(500), nullable=False, comment="用户上传时文件名"),
        sa.Column("stored_path", sa.String(1000), nullable=False, comment="分类后相对图片根目录路径"),
        sa.Column("match_status", sa.String(20), nullable=False, comment="图片匹配状态"),
        sa.Column("match_method", sa.String(40), nullable=True, comment="文件名匹配方式"),
        sa.Column("image_role", sa.String(40), nullable=True, comment="封面或社群图标准位"),
        sa.Column("package_id", sa.String(36), nullable=True, comment="匹配运营包ID"),
        sa.Column("channel_id", sa.String(36), nullable=True, comment="匹配频道ID"),
        sa.Column("drama_id", sa.String(36), nullable=True, comment="匹配剧目ID"),
        sa.Column("schedule_id", sa.String(36), nullable=True, comment="匹配排期ID"),
        sa.Column("output_path", sa.String(1000), nullable=True, comment="Logo成品相对图片根目录路径"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="未匹配或生成失败原因"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("match_status IN ('matched','unmatched','ambiguous')", name="ck_image_processing_items_valid_match_status"),
        sa.ForeignKeyConstraint(["run_id"], ["image_processing_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["package_id"], ["operation_packages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["drama_id"], ["dramas.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["schedule_id"], ["channel_schedule_entries.id"], ondelete="SET NULL"),
        comment="单张导入图片的分类与Logo成品记录",
    )
    op.create_index("ix_image_processing_items_run_status", "image_processing_items", ["run_id", "match_status"])

    comments = {
        "image_workspace_settings": "图片生产共享根目录设置",
        "channel_logo_profiles": "频道左右Logo与模板自动校准配置",
        "image_processing_runs": "批次图片分类与Logo生成运行记录",
        "image_processing_items": "单张导入图片的分类与Logo成品记录",
    }
    values = ",".join(
        "(%s,%s,%s,NOW())" % (repr(table), repr("__table__"), repr(comment))
        for table, comment in comments.items()
    )
    op.execute(sa.text("REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) VALUES " + values))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_comments WHERE table_name IN ('image_workspace_settings','channel_logo_profiles','image_processing_runs','image_processing_items')"))
    op.drop_index("ix_image_processing_items_run_status", table_name="image_processing_items")
    op.drop_table("image_processing_items")
    op.drop_index("ix_image_processing_runs_batch_created", table_name="image_processing_runs")
    op.drop_table("image_processing_runs")
    op.drop_table("channel_logo_profiles")
    op.drop_table("image_workspace_settings")
