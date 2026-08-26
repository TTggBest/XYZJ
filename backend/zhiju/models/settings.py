from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text
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
