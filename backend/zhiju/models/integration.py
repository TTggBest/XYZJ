from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TimestampMixin


class Integration(IdMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled','deprecated')", name="valid_status"),
        {"comment": "第三方服务类型定义"},
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, comment="系统内稳定集成代码")
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="集成显示名称")
    provider_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="服务提供方类型")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="集成状态")


class IntegrationAccount(IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('pending','active','expired','revoked','error','disabled')", name="valid_status"),
        UniqueConstraint("integration_id", "account_key", name="uq_integration_accounts_key"),
        Index("ix_integration_accounts_integration_status", "integration_id", "status"),
        {"comment": "第三方服务中的具体账号"},
    )

    integration_id: Mapped[str] = mapped_column(ForeignKey("integrations.id", ondelete="RESTRICT"), nullable=False, comment="第三方集成ID")
    account_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="系统内账号稳定标识")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="账号显示名称")
    external_account_id: Mapped[str | None] = mapped_column(String(255), comment="第三方平台账号ID")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="账号连接状态")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后验证时间")


class IntegrationCredential(IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (
        CheckConstraint("status IN ('active','expired','revoked','error')", name="valid_status"),
        UniqueConstraint("integration_account_id", "credential_type", name="uq_integration_credentials_type"),
        Index("ix_integration_credentials_account_status", "integration_account_id", "status"),
        {"comment": "第三方账号凭证引用，禁止保存密钥明文"},
    )

    integration_account_id: Mapped[str] = mapped_column(ForeignKey("integration_accounts.id", ondelete="CASCADE"), nullable=False, comment="第三方账号ID")
    credential_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="凭证类型")
    secret_reference: Mapped[str] = mapped_column(String(500), nullable=False, comment="外部Secret存储引用")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="凭证状态")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="凭证失效时间")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后验证时间")

