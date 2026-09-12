import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, MetaData, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    return str(uuid.uuid4())


class IdMixin:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id, comment="系统内部稳定主键"
    )


class TenantOwnedMixin:
    # Nullable while existing business tables are migrated in later tasks.
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True, comment="所属主账号ID"
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, comment="最后更新时间"
    )


def configure_tenant_relations(
    foreign_keys: tuple[tuple[str, str, str, str], ...],
    *,
    parent_tables: tuple[str, ...] = (),
) -> None:
    """Install the model-side constraints used by the relational tenant revisions."""
    for table_name in parent_tables:
        table = Base.metadata.tables[table_name]
        table.append_constraint(
            UniqueConstraint(
                "tenant_id", "id", name=f"uq_{table_name}_tenant_id_id"
            )
        )
    for table_name, column_name, parent_table, ondelete in foreign_keys:
        table = Base.metadata.tables[table_name]
        table.append_constraint(
            ForeignKeyConstraint(
                ["tenant_id", column_name],
                [f"{parent_table}.tenant_id", f"{parent_table}.id"],
                name=f"fk_{table_name}_t_{column_name}",
                ondelete=ondelete,
            )
        )
        Index(
            f"ix_{table_name}_t_{column_name}",
            table.c.tenant_id,
            table.c[column_name],
        )
