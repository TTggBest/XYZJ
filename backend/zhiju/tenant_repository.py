from collections.abc import Iterable
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models.base import TenantOwnedMixin


Entity = TypeVar("Entity", bound=TenantOwnedMixin)


def require_tenant_entity(
    session: Session, model: type[Entity], entity_id: str, lock: bool = False,
) -> Entity:
    return require_tenant_entities(session, model, [entity_id], lock=lock)[0]


def require_tenant_entities(
    session: Session, model: type[Entity], entity_ids: Iterable[str], lock: bool = False,
) -> list[Entity]:
    """Resolve the entire batch in input order; never return a partial match."""
    tenant_id = session.info.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="请选择当前主账号")
    ids = list(entity_ids)
    if not ids:
        return []
    statement = select(model).where(model.tenant_id == tenant_id, model.id.in_(set(ids)))
    if lock:
        statement = statement.with_for_update()
    rows = {row.id: row for row in session.scalars(statement).all()}
    if rows.keys() != set(ids):
        raise HTTPException(status_code=404, detail="数据不存在")
    return [rows[entity_id] for entity_id in ids]
