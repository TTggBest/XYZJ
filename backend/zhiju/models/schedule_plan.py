from datetime import datetime
from sqlalchemy import JSON, String, Text, DateTime, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from zhiju.models.base import Base, IdMixin, TenantOwnedMixin, TimestampMixin


class ChannelSchedulePlan(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = 'channel_schedule_plans'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id','channel_id'], ['channels.tenant_id','channels.id']),
        Index('ix_channel_schedule_plans_queue','tenant_id','host_id','status'),
    )
    channel_id: Mapped[str] = mapped_column(String(36), nullable=False)
    host_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='queued')
    dna_id: Mapped[str | None] = mapped_column(String(36))
    claim_id: Mapped[str | None] = mapped_column(String(36))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
