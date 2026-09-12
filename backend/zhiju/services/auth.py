from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal, _utc
from zhiju.models import (
    AppUser, AuthEvent, AuthSession, Device, DeviceUserBinding,
    Permission, RolePermission, Tenant, TenantMembership,
)
from zhiju.schemas.auth import AvailableMembership, CurrentDevice, CurrentTenant, CurrentUser
from zhiju.security import digest_token, hash_password, new_opaque_token, verify_password


_DUMMY_PASSWORD_HASH = hash_password(new_opaque_token())


@dataclass(frozen=True)
class LoginResult:
    principal: Principal
    expires_at: datetime
    token: str = field(repr=False)


def _available_memberships(session: Session, user_id: str, now: datetime):
    return session.execute(
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Tenant.status == "active",
            Tenant.lease_expires_at > now,
        )
        .order_by(TenantMembership.created_at, TenantMembership.id)
    ).all()


def password_login(
    session: Session, *, login_name: str, password: str, request_id: str,
    configured_device_id: str | None = None,
) -> LoginResult | None:
    """Stage login changes; the route owns the transaction, including failures."""
    now = datetime.now(timezone.utc)
    user = session.scalar(select(AppUser).where(AppUser.login_name == login_name).with_for_update())
    failure = None
    membership = None
    tenant = None
    locked = user is not None and user.locked_until is not None and _utc(user.locked_until) > now
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        failure = "invalid_credentials"
    elif locked:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        failure = "temporarily_locked"
    else:
        if user.locked_until is not None:
            user.locked_until = None
            user.failed_login_count = 0
        if user.status != "active":
            verify_password(password, _DUMMY_PASSWORD_HASH)
            failure = "user_inactive"
        elif user.lease_expires_at is not None and _utc(user.lease_expires_at) <= now:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            failure = "user_lease_expired"
        elif not verify_password(password, user.password_hash):
            failure = "invalid_credentials"
        elif user.platform_role != "super_admin":
            memberships = _available_memberships(session, user.id, now)
            if not memberships:
                failure = "no_available_membership"
            else:
                membership, tenant = memberships[0]

    if failure is not None:
        if user is not None and not locked:
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                user.locked_until = now + timedelta(minutes=15)
        session.add(AuthEvent(
            event_type="login", result="failure", actor_user_id=user.id if user else None,
            login_name=login_name, request_id=request_id, reason=failure, occurred_at=now,
        ))
        return None

    device = None
    binding = None
    configured_device_id = (configured_device_id or "").strip()
    if configured_device_id:
        device = session.get(Device, configured_device_id)
        if device is not None and device.status == "active":
            binding_query = select(DeviceUserBinding).join(
                Tenant, Tenant.id == DeviceUserBinding.tenant_id,
            ).where(
                DeviceUserBinding.device_id == device.id,
                DeviceUserBinding.user_id == user.id,
                DeviceUserBinding.status == "active",
                Tenant.status == "active",
                Tenant.lease_expires_at > now,
            ).where(
                (DeviceUserBinding.expires_at.is_(None))
                | (DeviceUserBinding.expires_at > now)
            )
            if tenant is not None:
                binding_query = binding_query.where(DeviceUserBinding.tenant_id == tenant.id)
            binding = session.scalar(binding_query.order_by(
                DeviceUserBinding.is_default.desc(), DeviceUserBinding.bound_at.desc(),
            ).limit(1))
        if binding is None:
            device = None
        elif tenant is None:
            tenant = session.get(Tenant, binding.tenant_id)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    token = new_opaque_token()
    auth_session = AuthSession(
        user_id=user.id, tenant_id=tenant.id if tenant else None,
        device_id=device.id if device else None, binding_id=binding.id if binding else None,
        token_digest=digest_token(token), status="active", expires_at=now + timedelta(hours=8),
        created_at=now, last_seen_at=now,
    )
    session.add(auth_session)
    session.flush()
    if binding is not None:
        binding.auto_login_enabled = True
        binding.last_used_at = now
    session.add(AuthEvent(
        event_type="login", result="success", actor_user_id=user.id,
        actor_device_id=device.id if device else None,
        tenant_id=auth_session.tenant_id, session_id=auth_session.id,
        request_id=request_id, login_name=login_name, occurred_at=now,
    ))
    membership_role = membership.role_code if membership else None
    roles = {role for role in (membership_role, user.platform_role) if role is not None}
    permissions = frozenset(session.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_code.in_(roles))
    ))
    return LoginResult(
        principal=Principal(
            user_id=user.id, tenant_id=auth_session.tenant_id, membership_role=membership_role,
            platform_role=user.platform_role, device_id=device.id if device else None,
            device_trust_level=device.trust_level if device else "normal",
            permissions=permissions,
        ),
        expires_at=auth_session.expires_at, token=token,
    )


def current_user(session: Session, principal: Principal) -> CurrentUser:
    user = session.get(AppUser, principal.user_id)
    tenant = session.get(Tenant, principal.tenant_id) if principal.tenant_id else None
    device = session.get(Device, principal.device_id) if principal.device_id else None
    now = datetime.now(timezone.utc)
    memberships = _available_memberships(session, principal.user_id, now)
    switchable = list(session.scalars(select(Tenant).where(
        Tenant.status == "active", Tenant.lease_expires_at > now,
    ).order_by(Tenant.short_name, Tenant.id))) if principal.platform_role == "super_admin" else [
        item_tenant for _, item_tenant in memberships
    ]
    return CurrentUser(
        user_id=user.id, display_name=user.display_name, login_name=user.login_name,
        platform_role=principal.platform_role, tenant_id=principal.tenant_id,
        membership_role=principal.membership_role,
        current_tenant=CurrentTenant(
            id=tenant.id, company_name=tenant.company_name, short_name=tenant.short_name,
        ) if tenant else None,
        memberships=[AvailableMembership(
            tenant_id=item_tenant.id, company_name=item_tenant.company_name,
            short_name=item_tenant.short_name, role_code=membership.role_code,
        ) for membership, item_tenant in memberships],
        switchable_tenants=[CurrentTenant(
            id=item.id, company_name=item.company_name, short_name=item.short_name,
        ) for item in switchable],
        device=CurrentDevice(
            id=device.id, name=device.name, display_name=device.alias or device.name,
            trust_level=principal.device_trust_level,
        ) if device else None,
        permissions=sorted(principal.permissions),
    )


def logout(session: Session, *, token: str | None, request_id: str) -> None:
    if not token:
        return
    auth_session = session.scalar(select(AuthSession).where(
        AuthSession.token_digest == digest_token(token),
    ).with_for_update())
    if auth_session is None:
        return
    now = datetime.now(timezone.utc)
    if auth_session.status != "revoked":
        auth_session.status = "revoked"
        auth_session.revoked_at = now
        auth_session.revoke_reason = "logout"
    if auth_session.binding_id is not None:
        binding = session.scalar(select(DeviceUserBinding).where(
            DeviceUserBinding.id == auth_session.binding_id,
            DeviceUserBinding.status == "active",
        ).with_for_update())
        if binding is not None:
            binding.auto_login_enabled = False
    session.add(AuthEvent(
        event_type="logout", result="success", actor_user_id=auth_session.user_id,
        actor_device_id=auth_session.device_id, tenant_id=auth_session.tenant_id,
        session_id=auth_session.id, request_id=request_id, occurred_at=now,
    ))


def switch_tenant(
    session: Session, principal: Principal, *, token: str, tenant_id: str, request_id: str,
) -> None:
    if principal.platform_role != "super_admin":
        raise HTTPException(status_code=403, detail="仅超级管理员可以切换主账号")
    now = datetime.now(timezone.utc)
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="主账号不存在")
    if tenant.status != "active" or _utc(tenant.lease_expires_at) <= now:
        raise HTTPException(status_code=403, detail="主账号已停用或租约已到期")
    auth_session = session.scalar(select(AuthSession).where(
        AuthSession.token_digest == digest_token(token), AuthSession.user_id == principal.user_id,
        AuthSession.status == "active",
    ).with_for_update())
    if auth_session is None:
        raise HTTPException(status_code=401, detail="请先登录")
    previous_tenant_id = auth_session.tenant_id
    auth_session.tenant_id = tenant.id
    session.add(AuthEvent(
        event_type="tenant_switch", result="success", actor_user_id=principal.user_id,
        actor_device_id=principal.device_id, tenant_id=tenant.id, session_id=auth_session.id,
        request_id=request_id, target_type="tenant", target_id=tenant.id, occurred_at=now,
        detail=json.dumps({"from_tenant_id": previous_tenant_id, "to_tenant_id": tenant.id}),
    ))
    session.flush()
