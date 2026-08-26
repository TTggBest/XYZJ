from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zhiju.models.base import Base, IdMixin, TimestampMixin


class Skill(IdMixin, TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','disabled','deprecated')", name="valid_status"
        ),
        Index("ix_skills_category_status", "category", "status"),
        {"comment": "生产能力Skill稳定定义"},
    )

    code: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, comment="系统内稳定Skill代码"
    )
    name: Mapped[str] = mapped_column(
        String(160), nullable=False, comment="Skill显示名称"
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False, comment="Skill业务用途")
    category: Mapped[str] = mapped_column(
        String(60), nullable=False, comment="Skill能力分类"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", comment="Skill生命周期状态"
    )

    versions: Mapped[list[SkillVersion]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class SkillVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint(
            "status IN ('draft','published','superseded','archived')",
            name="valid_status",
        ),
        CheckConstraint(
            "is_current IS NULL OR (is_current = 1 AND status = 'published')",
            name="current_version_must_be_published",
        ),
        UniqueConstraint("skill_id", "version_number", name="uq_skill_versions_number"),
        UniqueConstraint("skill_id", "content_sha256", name="uq_skill_versions_content"),
        UniqueConstraint("skill_id", "is_current", name="uq_skill_versions_current"),
        Index("ix_skill_versions_skill_status", "skill_id", "status"),
        {"comment": "Skill双语正文不可变版本"},
    )

    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, comment="Skill稳定ID"
    )
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Skill内部递增版本号"
    )
    body_zh_cn: Mapped[str] = mapped_column(
        Text, nullable=False, comment="供业务审核和编辑的中文正文"
    )
    body_original: Mapped[str] = mapped_column(
        Text, nullable=False, comment="供正式执行的原文正文"
    )
    content_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="双语正文内容SHA256"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft", comment="Skill版本状态"
    )
    is_current: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="当前发布版本唯一标记，历史版本为空"
    )
    change_summary: Mapped[str | None] = mapped_column(Text, comment="版本修改说明")
    created_by: Mapped[str | None] = mapped_column(
        String(120), comment="版本创建操作者标识"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="版本发布时间"
    )

    skill: Mapped[Skill] = relationship(back_populates="versions")
