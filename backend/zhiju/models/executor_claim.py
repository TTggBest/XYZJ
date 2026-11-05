"""Execution capacity remains reserved until the owning CLI has stopped."""
from datetime import datetime
from sqlalchemy import String,DateTime,Index,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from zhiju.models.base import Base,IdMixin,TenantOwnedMixin,TimestampMixin


class ExecutorClaim(TenantOwnedMixin,IdMixin,TimestampMixin,Base):
    __tablename__='executor_claims'
    __table_args__=(UniqueConstraint('tenant_id','claim_id'),Index('ix_executor_claims_capacity','tenant_id','released_at'))
    task_type:Mapped[str]=mapped_column(String(40),nullable=False)
    run_id:Mapped[str]=mapped_column(String(36),nullable=False)
    host_id:Mapped[str]=mapped_column(String(36),nullable=False)
    claim_id:Mapped[str]=mapped_column(String(36),nullable=False)
    released_at:Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
