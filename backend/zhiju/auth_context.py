from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from zhiju.database import TenantSession, get_db, open_tenant_session
from zhiju.models import (
    AppUser,
    AuthSession,
    Device,
    DeviceUserBinding,
    Permission,
    RolePermission,
    Tenant,
    TenantMembership,
)
from zhiju.security import digest_token


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str | None
    membership_role: str | None
    platform_role: str | None
    device_id: str | None
    device_trust_level: str
    permissions: frozenset[str]
    session_id: str | None = None


def _utc(value: datetime) -> datetime:
    # MySQL DATETIME (and SQLite tests) return naive UTC timestamps.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def get_optional_principal(
    request: Request, session: Session = Depends(get_db),
) -> Principal | None:
    # A caller transaction may already contain flushed work, even when dirty is empty.
    allow_heartbeat = not session.in_transaction()
    # Authentication reads must not flush business changes pending in the caller.
    with session.no_autoflush:
        principal = _resolve_principal(request, session, allow_heartbeat=allow_heartbeat)
    request.state.principal = principal
    return principal


def _resolve_principal(
    request: Request, session: Session, *, allow_heartbeat: bool,
) -> Principal | None:
    token = request.cookies.get("zhiju_session")
    if not token:
        return None

    auth_session = session.scalar(select(AuthSession).where(
        AuthSession.token_digest == digest_token(token),
        AuthSession.status == "active",
    ))
    now = datetime.now(timezone.utc)
    if auth_session is None or _utc(auth_session.expires_at) <= now:
        return None

    user = session.get(AppUser, auth_session.user_id)
    if user is None or user.status != "active":
        return None
    if user.lease_expires_at is not None and _utc(user.lease_expires_at) <= now:
        return None

    device = session.get(Device, auth_session.device_id) if auth_session.device_id else None
    if auth_session.device_id is not None and (device is None or device.status != "active"):
        return None

    if auth_session.binding_id is not None:
        binding = session.get(DeviceUserBinding, auth_session.binding_id)
        if (
            binding is None or binding.status != "active"
            or binding.user_id != auth_session.user_id
            or binding.device_id != auth_session.device_id
            or (binding.expires_at is not None and _utc(binding.expires_at) <= now)
        ):
            return None
        # The binding's origin tenant remains unchanged when a super admin switches tenants.

    membership_role = None
    if auth_session.tenant_id is not None:
        tenant = session.get(Tenant, auth_session.tenant_id)
        if tenant is None or tenant.status != "active" or _utc(tenant.lease_expires_at) <= now:
            raise HTTPException(status_code=403, detail="主账号已停用或租约已到期")
        membership = session.scalar(select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == tenant.id,
            TenantMembership.status == "active",
        ))
        if membership is not None:
            membership_role = membership.role_code

    # Platform admins enter tenant context as themselves, without an owner membership.
    if membership_role is None and user.platform_role != "super_admin":
        raise HTTPException(status_code=403, detail="没有当前主账号的有效成员权限")

    roles = {role for role in (membership_role, user.platform_role) if role is not None}
    permissions = frozenset(session.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_code.in_(roles))
    ))
    principal = Principal(
        user_id=user.id,
        tenant_id=auth_session.tenant_id,
        membership_role=membership_role,
        platform_role=user.platform_role,
        device_id=device.id if device else None,
        device_trust_level=device.trust_level if device else "normal",
        permissions=permissions,
        session_id=auth_session.id,
    )
    if allow_heartbeat and _utc(auth_session.last_seen_at) <= now - timedelta(minutes=5):
        # Own a short transaction; never commit the caller's unit of work.
        with session.get_bind().engine.begin() as connection:
            connection.execute(update(AuthSession).where(
                AuthSession.id == auth_session.id,
                AuthSession.last_seen_at <= now - timedelta(minutes=5),
            ).values(last_seen_at=now))
    return principal


def get_current_principal(
    request: Request, session: Session = Depends(get_db),
) -> Principal:
    principal = get_optional_principal(request, session)
    if principal is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def get_tenant_db(
    principal: Principal = Depends(get_current_principal),
) -> Generator[TenantSession, None, None]:
    with open_tenant_session(principal) as session:
        yield session
