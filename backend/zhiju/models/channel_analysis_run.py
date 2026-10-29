from datetime import datetime
from sqlalchemy import JSON, String, Text, DateTime, ForeignKeyConstraint, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from zhiju.models.base import Base, IdMixin, TenantOwnedMixin, TimestampMixin


class ChannelAnalysisRun(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = 'channel_analysis_runs'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'id', name='uq_channel_analysis_runs_tenant_id_id'),
        ForeignKeyConstraint(['tenant_id', 'channel_id'], ['channels.tenant_id', 'channels.id']),
        Index('ix_channel_analysis_runs_queue', 'tenant_id', 'status', 'host_id'),
    )
    channel_id: Mapped[str] = mapped_column(String(36), nullable=False)
    host_id: Mapped[str] = mapped_column(String(36), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='draft')
    phase: Mapped[str] = mapped_column(String(40), nullable=False, default='materials')
    claim_id: Mapped[str | None] = mapped_column(String(36))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    materials: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    attempts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    report_id: Mapped[str | None] = mapped_column(String(36))
    dna_id: Mapped[str | None] = mapped_column(String(36))
    mirror_status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending')
