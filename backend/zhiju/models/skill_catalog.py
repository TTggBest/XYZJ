"""Tenant skill categories and complete version archives."""
from sqlalchemy import String, Text, Integer, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import Mapped, mapped_column
from zhiju.models.base import Base, IdMixin, TenantOwnedMixin, TimestampMixin

class SkillCategory(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = 'skill_categories'
    __table_args__ = (UniqueConstraint('tenant_id', 'name'),)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='', nullable=False)
    default_version_id: Mapped[str | None] = mapped_column(String(36))

class SkillBundleVersion(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = 'skill_bundle_versions'
    __table_args__ = (UniqueConstraint('tenant_id', 'category_id', 'label', 'revision'),)
    category_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='draft')
    change_summary: Mapped[str] = mapped_column(Text, default='', nullable=False)
    archive: Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB(), 'mysql'), nullable=False)
