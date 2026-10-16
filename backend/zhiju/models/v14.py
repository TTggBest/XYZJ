"""Fixed V14 execution state. Existing Feishu models are deliberately unchanged."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TenantOwnedMixin, TimestampMixin


class V14Setting(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "v14_settings"
    __table_args__ = (UniqueConstraint("tenant_id"),)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class V14Run(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "v14_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "work_order_id"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "work_order_id"], ["work_orders.tenant_id", "work_orders.id"]),
        ForeignKeyConstraint(["tenant_id", "package_id"], ["operation_packages.tenant_id", "operation_packages.id"]),
        CheckConstraint("status IN ('queued','running','interrupted','needs_user_review','cancelled','text_ready')", name="valid_status"),
    )
    work_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    package_id: Mapped[str] = mapped_column(String(36), nullable=False)
    host_id: Mapped[str] = mapped_column(String(36), nullable=False)
    account_profile: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    claim_id: Mapped[str | None] = mapped_column(String(36))
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    rules_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class V14Attempt(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "v14_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "run_id"], ["v14_runs.tenant_id", "v14_runs.id"]),
        UniqueConstraint("run_id", "node_type", "sequence"),
        CheckConstraint("outcome IN ('running','accepted','content_error','system_error','interrupted')", name="valid_outcome"),
    )
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    claim_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    payload: Mapped[dict | None] = mapped_column(JSON)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
