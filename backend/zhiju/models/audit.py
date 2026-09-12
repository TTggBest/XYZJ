from datetime import datetime
from typing import ClassVar

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, event
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TenantOwnedMixin


class AuditEvent(TenantOwnedMixin, IdMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_audit_events_tenant_idempotency"),
        Index("ix_audit_events_entity_time", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_actor_time", "actor_type", "actor_id", "occurred_at"),
        {"comment": "业务对象变更审计流水"},
    )

    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="操作者类型")
    actor_id: Mapped[str | None] = mapped_column(String(36), comment="操作者内部ID")
    action: Mapped[str] = mapped_column(String(80), nullable=False, comment="操作动作")
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, comment="业务对象类型")
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="业务对象内部ID")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="请求追踪ID")
    idempotency_key: Mapped[str | None] = mapped_column(String(160), comment="幂等键")
    change_summary: Mapped[str | None] = mapped_column(Text, comment="不含密钥的变更摘要")
    occurred_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="操作发生时间")

    PLATFORM_ENTITY_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "app_icon_setting",
            "device",
            "integration",
            "language",
            "publish_cadence_template",
            "publish_cadence_template_slot",
            "runtime_package_build",
            "schema_comment",
            "skill",
            "skill_version",
        }
    )


@event.listens_for(AuditEvent, "before_insert")
def _require_business_audit_tenant(_mapper, _connection, event_row: AuditEvent) -> None:
    if event_row.tenant_id is None and event_row.entity_type not in AuditEvent.PLATFORM_ENTITY_TYPES:
        raise ValueError("业务审计事件必须提供 tenant_id")


class SchemaComment(Base):
    __tablename__ = "schema_comments"
    __table_args__ = ({"comment": "数据库表字段中文说明"},)

    table_name: Mapped[str] = mapped_column(String(128), primary_key=True, comment="表名")
    column_name: Mapped[str] = mapped_column(String(128), primary_key=True, comment="字段名，表说明使用__table__")
    chinese_comment: Mapped[str] = mapped_column(Text, nullable=False, comment="中文说明")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="最后更新时间")
