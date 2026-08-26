from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TimestampMixin


class DemoDataBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "demo_data_batches"
    __table_args__ = (
        CheckConstraint("status IN ('active','deleted')", name="valid_status"),
        {"comment": "可整体删除的本机演示数据批次"},
    )

    batch_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="演示批次稳定代码")
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, comment="演示数据来源说明")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="导入的业务行数")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="演示任务起始日期")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="演示任务结束日期")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="批次状态")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="一键删除完成时间")


class DemoDataEntity(IdMixin, TimestampMixin, Base):
    __tablename__ = "demo_data_entities"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_demo_data_entities_entity"),
        Index("ix_demo_data_entities_batch_type", "batch_id", "entity_type"),
        {"comment": "演示批次实际创建并拥有的数据库实体"},
    )

    batch_id: Mapped[str] = mapped_column(ForeignKey("demo_data_batches.id", ondelete="CASCADE"), nullable=False, comment="所属演示批次ID")
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, comment="实体类型")
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="实体内部ID")
    owned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", comment="删除批次时是否删除该实体")
