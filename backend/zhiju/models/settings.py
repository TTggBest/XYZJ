from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TimestampMixin


class RuntimePackageBuild(IdMixin, TimestampMixin, Base):
    __tablename__ = "runtime_package_builds"
    __table_args__ = (
        CheckConstraint("status IN ('building','succeeded','failed')", name="valid_status"),
        Index("ix_runtime_package_builds_status_created", "status", "created_at"),
        {"comment": "智矩仅代码运行包构建记录"},
    )

    build_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, comment="递增构建序号")
    version: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, comment="运行包版本")
    target_environment: Mapped[str] = mapped_column(String(30), nullable=False, comment="目标运行环境")
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="构建状态")
    artifact_path: Mapped[str | None] = mapped_column(String(1000), comment="运行包本机绝对路径")
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="运行包文件数量")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="运行包字节大小")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="构建开始时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="构建完成时间")
    error_message: Mapped[str | None] = mapped_column(Text, comment="构建失败原因")


class AppIconSetting(TimestampMixin, Base):
    __tablename__ = "app_icon_settings"
    __table_args__ = (
        CheckConstraint("source_type IN ('default','custom')", name="valid_source_type"),
        {"comment": "智矩当前应用图标设置"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="固定设置主键")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="图标来源类型")
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="当前图标源文件路径")
    original_filename: Mapped[str | None] = mapped_column(String(255), comment="上传时原始文件名")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="最近应用时间")


class ImageWorkspaceSetting(TimestampMixin, Base):
    __tablename__ = "image_workspace_settings"
    __table_args__ = ({"comment": "图片生产共享根目录设置"},)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="固定设置主键")
    root_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="共享根目录下的相对路径或本机绝对路径")
    persistent_dir_name: Mapped[str] = mapped_column(String(120), nullable=False, server_default="系统素材", comment="不可随产物清理的必备素材目录名")
    output_dir_name: Mapped[str] = mapped_column(String(120), nullable=False, server_default="用户产物", comment="可清理的用户产物目录名")


class ChannelLogoProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_logo_profiles"
    __table_args__ = (
        CheckConstraint("status IN ('calibrated','failed')", name="valid_status"),
        UniqueConstraint("channel_id", name="uq_channel_logo_profiles_channel_id"),
        {"comment": "频道左右Logo与模板自动校准配置"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="校准状态")
    left_logo_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="左Logo相对图片根目录路径")
    right_logo_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="右Logo相对图片根目录路径")
    template_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="校准模板相对图片根目录路径")
    config_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="自动生成的Logo配置相对路径")
    canvas_width: Mapped[int] = mapped_column(Integer, nullable=False, comment="模板画布宽度")
    canvas_height: Mapped[int] = mapped_column(Integer, nullable=False, comment="模板画布高度")
    calibrated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="最近自动校准时间")


class ImageProcessingRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "image_processing_runs"
    __table_args__ = (
        CheckConstraint("status IN ('processing','classified','partially_classified','logo_ready','partially_generated','failed')", name="valid_status"),
        Index("ix_image_processing_runs_batch_created", "batch_id", "created_at"),
        {"comment": "批次图片分类与Logo生成运行记录"},
    )

    batch_id: Mapped[str] = mapped_column(ForeignKey("production_batches.id", ondelete="RESTRICT"), nullable=False, comment="生产批次ID")
    status: Mapped[str] = mapped_column(String(30), nullable=False, comment="处理状态")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="导入图片数")
    matched_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="成功分类图片数")
    unmatched_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="未匹配图片数")
    generated_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="已生成Logo成品数")
    manifest_path: Mapped[str | None] = mapped_column(String(1000), comment="处理报告相对图片根目录路径")
    error_message: Mapped[str | None] = mapped_column(Text, comment="处理失败原因")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近处理完成时间")


class ImageProcessingItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "image_processing_items"
    __table_args__ = (
        CheckConstraint("match_status IN ('matched','unmatched','ambiguous')", name="valid_match_status"),
        Index("ix_image_processing_items_run_status", "run_id", "match_status"),
        {"comment": "单张导入图片的分类与Logo成品记录"},
    )

    run_id: Mapped[str] = mapped_column(ForeignKey("image_processing_runs.id", ondelete="CASCADE"), nullable=False, comment="图片处理运行ID")
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="用户上传时文件名")
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="分类后相对图片根目录路径")
    match_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="图片匹配状态")
    match_method: Mapped[str | None] = mapped_column(String(40), comment="文件名匹配方式")
    image_role: Mapped[str | None] = mapped_column(String(40), comment="封面或社群图标准位")
    package_id: Mapped[str | None] = mapped_column(ForeignKey("operation_packages.id", ondelete="SET NULL"), comment="匹配运营包ID")
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), comment="匹配频道ID")
    drama_id: Mapped[str | None] = mapped_column(ForeignKey("dramas.id", ondelete="SET NULL"), comment="匹配剧目ID")
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="SET NULL"), comment="匹配排期ID")
    output_path: Mapped[str | None] = mapped_column(String(1000), comment="Logo成品相对图片根目录路径")
    error_message: Mapped[str | None] = mapped_column(Text, comment="未匹配或生成失败原因")
