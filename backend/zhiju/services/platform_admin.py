"""Identity administration. Callers own the transaction, including audit and enrollment."""

from collections.abc import Callable
from datetime import datetime, timezone
import json

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal, _utc
from zhiju.models import AppUser, AuthEvent, AuthSession, Device, DeviceUserBinding, Tenant, TenantMembership
from zhiju.permissions import require_super_code_machine
from zhiju.schemas.platform_admin import (
    AccountView, BindingRevoke, DeviceBindingCreate, DeviceBindingView, NewAccount,
    OwnerTransfer, PasswordReset, SuperAdminTransfer, TenantCreate, TenantUpdate,
    TenantView, UserCreate, UserUpdate, UserView,
)
from zhiju.security import digest_token, hash_password, new_opaque_token


def _audit(session, principal, *, event_type, target_type, target_id, tenant_id, request_id,
           detail=None, reason=None):
    session.add(AuthEvent(
        actor_user_id=principal.user_id, actor_device_id=principal.device_id,
        tenant_id=tenant_id, request_id=request_id, event_type=event_type, result="success",
        target_type=target_type, target_id=target_id,
        detail=json.dumps(detail) if detail is not None else None,
        reason=reason, occurred_at=datetime.now(timezone.utc),
    ))


def _revoke_sessions(session, *criteria, reason):
    session.execute(update(AuthSession).where(AuthSession.status == "active", *criteria).values(
        status="revoked", revoked_at=datetime.now(timezone.utc), revoke_reason=reason,
    ))


def _tenant(session, tenant_id, *, lock=False):
    query = select(Tenant).where(Tenant.id == tenant_id)
    tenant = session.scalar(query.with_for_update() if lock else query)
    if tenant is None:
        raise HTTPException(status_code=404, detail="主账号不存在")
    return tenant


def _active_account(account, *, label):
    now = datetime.now(timezone.utc)
    if account.status != "active" or (
        account.lease_expires_at is not None and _utc(account.lease_expires_at) <= now
    ):
        raise HTTPException(status_code=409, detail=f"{label}已停用或租约已到期")


def _new_account(session, principal, payload: NewAccount):
    now = datetime.now(timezone.utc)
    if payload.lease_expires_at is not None and payload.lease_expires_at <= now:
        raise HTTPException(status_code=422, detail="新用户租约必须晚于当前时间")
    if session.scalar(select(AppUser.id).where(AppUser.login_name == payload.login_name)):
        raise HTTPException(status_code=409, detail="登录名已存在")
    user = AppUser(
        display_name=payload.display_name, login_name=payload.login_name,
        password_hash=hash_password(payload.password.get_secret_value()),
        lease_expires_at=payload.lease_expires_at, password_changed_at=now,
        created_by_user_id=principal.user_id,
    )
    session.add(user)
    session.flush()
    return user


def list_tenants(session: Session, principal: Principal) -> list[TenantView]:
    require_super_code_machine(principal)
    return [TenantView.model_validate(tenant) for tenant in session.scalars(
        select(Tenant).order_by(Tenant.created_at, Tenant.id)
    )]


def create_tenant(session: Session, principal: Principal, payload: TenantCreate, *, request_id: str) -> TenantView:
    require_super_code_machine(principal)
    if payload.lease_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="新主账号租约必须晚于当前时间")
    owner = _new_account(session, principal, payload.owner)
    tenant = Tenant(**payload.model_dump(exclude={"owner"}), created_by_user_id=principal.user_id)
    if tenant.status == "suspended":
        tenant.suspended_at = datetime.now(timezone.utc)
    session.add(tenant)
    session.flush()
    session.add(TenantMembership(
        user_id=owner.id, tenant_id=tenant.id, role_code="owner", status="active",
        created_by_user_id=principal.user_id,
    ))
    _audit(session, principal, event_type="tenant_create", target_type="tenant", target_id=tenant.id,
           tenant_id=tenant.id, request_id=request_id, detail={"owner_user_id": owner.id})
    session.flush()
    return TenantView.model_validate(tenant)


def _set_account_fields(account, changes):
    for field, value in changes.items():
        setattr(account, field, value)
    if "status" in changes:
        account.suspended_at = datetime.now(timezone.utc) if account.status == "suspended" else None
        if account.status == "active":
            account.suspended_reason = None


def update_tenant(session: Session, principal: Principal, tenant_id: str, payload: TenantUpdate,
                  *, request_id: str) -> TenantView:
    require_super_code_machine(principal)
    tenant = _tenant(session, tenant_id, lock=True)
    now = datetime.now(timezone.utc)
    was_expired = _utc(tenant.lease_expires_at) <= now
    changes = payload.model_dump(exclude_unset=True)
    _set_account_fields(tenant, changes)
    if was_expired or tenant.status != "active" or _utc(tenant.lease_expires_at) <= now:
        _revoke_sessions(session, AuthSession.tenant_id == tenant.id, reason="tenant_unavailable")
    _audit(session, principal, event_type="tenant_update", target_type="tenant", target_id=tenant.id,
           tenant_id=tenant.id, request_id=request_id, detail={"changed_fields": sorted(changes)})
    session.flush()
    return TenantView.model_validate(tenant)


def transfer_owner(session: Session, principal: Principal, tenant_id: str, payload: OwnerTransfer,
                   *, request_id: str) -> TenantView:
    require_super_code_machine(principal)
    tenant = _tenant(session, tenant_id, lock=True)
    owners = list(session.scalars(select(TenantMembership).where(
        TenantMembership.tenant_id == tenant_id, TenantMembership.role_code == "owner",
        TenantMembership.status == "active",
    ).with_for_update()))
    if len(owners) != 1:
        raise HTTPException(status_code=409, detail="主账号所有者关系异常")
    user, membership = _member(session, tenant_id, payload.user_id)
    if user.id == owners[0].user_id:
        raise HTTPException(status_code=409, detail="目标已经是所有者")
    _active_account(user, label="目标用户")
    if membership.status != "active" or user.platform_role is not None:
        raise HTTPException(status_code=409, detail="目标必须是有效的普通主账号成员")
    previous_user_id = owners[0].user_id
    owners[0].role_code = payload.previous_owner_role
    membership.role_code = "owner"
    _audit(session, principal, event_type="owner_transfer", target_type="tenant", target_id=tenant.id,
           tenant_id=tenant.id, request_id=request_id,
           detail={"from_user_id": previous_user_id, "to_user_id": user.id})
    session.flush()
    return TenantView.model_validate(tenant)


def _user_scope(session, principal, tenant_id, *, lock=False):
    if tenant_id is not None:
        require_super_code_machine(principal)
    else:
        if principal.membership_role != "owner" or principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="仅当前主账号所有者可以管理子账号")
        tenant_id = principal.tenant_id
    return _tenant(session, tenant_id, lock=lock)


def _member(session, tenant_id, user_id):
    result = session.execute(select(AppUser, TenantMembership).join(
        TenantMembership, TenantMembership.user_id == AppUser.id,
    ).where(TenantMembership.tenant_id == tenant_id, AppUser.id == user_id).with_for_update()).first()
    if result is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return result


def _user_view(user, membership):
    return UserView(**AccountView.model_validate(user).model_dump(), tenant_id=membership.tenant_id,
                    role_code=membership.role_code, membership_status=membership.status)


def _check_managed_user(session, user, membership, *, platform, global_fields=False):
    if user.platform_role is not None or (not platform and membership.role_code == "owner"):
        raise HTTPException(status_code=403, detail="此入口不能修改所有者或平台账号")
    if not platform and global_fields and session.scalar(select(TenantMembership.id).where(
        TenantMembership.user_id == user.id, TenantMembership.tenant_id != membership.tenant_id,
    ).limit(1)):
        raise HTTPException(status_code=403, detail="共享账号的全局资料和密码仅允许平台管理")


def list_users(session: Session, principal: Principal, *, tenant_id: str | None = None) -> list[UserView]:
    tenant = _user_scope(session, principal, tenant_id)
    rows = session.execute(select(AppUser, TenantMembership).join(
        TenantMembership, TenantMembership.user_id == AppUser.id,
    ).where(TenantMembership.tenant_id == tenant.id).order_by(AppUser.created_at, AppUser.id))
    return [_user_view(user, membership) for user, membership in rows]


def create_user(session: Session, principal: Principal, payload: UserCreate,
                *, request_id: str, tenant_id: str | None = None) -> UserView:
    tenant = _user_scope(session, principal, tenant_id, lock=True)
    user = _new_account(session, principal, payload)
    _set_account_fields(user, {"status": payload.status})
    membership = TenantMembership(user_id=user.id, tenant_id=tenant.id, role_code=payload.role_code,
                                  status="active", created_by_user_id=principal.user_id)
    session.add(membership)
    _audit(session, principal, event_type="user_create", target_type="user", target_id=user.id,
           tenant_id=tenant.id, request_id=request_id, detail={"role_code": payload.role_code})
    session.flush()
    return _user_view(user, membership)


def update_user(session: Session, principal: Principal, user_id: str, payload: UserUpdate,
                *, request_id: str, tenant_id: str | None = None) -> UserView:
    tenant = _user_scope(session, principal, tenant_id, lock=True)
    user, membership = _member(session, tenant.id, user_id)
    changes = payload.model_dump(exclude_unset=True)
    global_changes = {key: value for key, value in changes.items() if key not in {"role_code", "membership_status"}}
    _check_managed_user(session, user, membership, platform=tenant_id is not None,
                        global_fields=bool(global_changes))
    if membership.role_code == "owner" and (
        "role_code" in changes or changes.get("membership_status") == "suspended"
    ):
        raise HTTPException(status_code=409, detail="必须使用所有者转交操作保留唯一所有者")
    now = datetime.now(timezone.utc)
    was_expired = user.lease_expires_at is not None and _utc(user.lease_expires_at) <= now
    _set_account_fields(user, global_changes)
    if "role_code" in changes:
        membership.role_code = changes["role_code"]
    if "membership_status" in changes:
        membership.status = changes["membership_status"]
    if was_expired or user.status != "active" or (
        user.lease_expires_at is not None and _utc(user.lease_expires_at) <= now
    ):
        _revoke_sessions(session, AuthSession.user_id == user.id, reason="user_unavailable")
    elif membership.status != "active":
        _revoke_sessions(session, AuthSession.user_id == user.id, AuthSession.tenant_id == tenant.id,
                         reason="membership_suspended")
    _audit(session, principal, event_type="user_update", target_type="user", target_id=user.id,
           tenant_id=tenant.id, request_id=request_id, detail={"changed_fields": sorted(changes)})
    session.flush()
    return _user_view(user, membership)


def reset_password(session: Session, principal: Principal, user_id: str, payload: PasswordReset,
                   *, request_id: str, tenant_id: str | None = None) -> UserView:
    tenant = _user_scope(session, principal, tenant_id, lock=True)
    user, membership = _member(session, tenant.id, user_id)
    _check_managed_user(session, user, membership, platform=tenant_id is not None, global_fields=True)
    user.password_hash = hash_password(payload.password.get_secret_value())
    user.password_changed_at = datetime.now(timezone.utc)
    user.failed_login_count = 0
    user.locked_until = None
    _revoke_sessions(session, AuthSession.user_id == user.id, reason="password_reset")
    _audit(session, principal, event_type="password_reset", target_type="user", target_id=user.id,
           tenant_id=tenant.id, request_id=request_id)
    session.flush()
    return _user_view(user, membership)


def transfer_super_admin(session: Session, principal: Principal, payload: SuperAdminTransfer,
                         *, request_id: str) -> AccountView:
    require_super_code_machine(principal)
    supers = list(session.scalars(select(AppUser).where(AppUser.platform_role == "super_admin").with_for_update()))
    if len(supers) != 1 or supers[0].id != principal.user_id:
        raise HTTPException(status_code=409, detail="平台必须存在唯一的当前超级管理员")
    previous = supers[0]
    if payload.new_user is not None:
        raise HTTPException(status_code=409, detail="新账号尚无可用的超级代码机会话，不能转交超级管理员")
    successor = session.scalar(select(AppUser).where(AppUser.id == payload.user_id).with_for_update())
    if successor is None:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    if successor.id == previous.id or session.scalar(select(TenantMembership.id).where(
        TenantMembership.user_id == successor.id,
    ).limit(1)):
        raise HTTPException(status_code=409, detail="新超级管理员必须是另一个独立于主账号的用户")
    _active_account(successor, label="目标用户")
    now = datetime.now(timezone.utc)
    usable_session_id = session.scalar(select(AuthSession.id).join(
        DeviceUserBinding, DeviceUserBinding.id == AuthSession.binding_id,
    ).join(Device, Device.id == AuthSession.device_id).outerjoin(
        Tenant, Tenant.id == AuthSession.tenant_id,
    ).where(
        AuthSession.user_id == successor.id, AuthSession.status == "active", AuthSession.expires_at > now,
        DeviceUserBinding.user_id == successor.id, DeviceUserBinding.device_id == Device.id,
        DeviceUserBinding.status == "active", DeviceUserBinding.auto_login_enabled.is_(True),
        or_(DeviceUserBinding.expires_at.is_(None), DeviceUserBinding.expires_at > now),
        Device.status == "active", Device.trust_level == "super_code_machine",
        or_(AuthSession.tenant_id.is_(None), and_(Tenant.status == "active", Tenant.lease_expires_at > now)),
    ).limit(1).with_for_update())
    if usable_session_id is None:
        raise HTTPException(status_code=409, detail="目标用户尚无可用的超级代码机绑定会话，不能转交超级管理员")
    previous.platform_role = None
    successor.platform_role = "super_admin"
    _revoke_sessions(session, AuthSession.user_id == previous.id, reason="super_admin_transfer")
    _audit(session, principal, event_type="super_admin_transfer", target_type="user", target_id=successor.id,
           tenant_id=None, request_id=request_id, detail={"from_user_id": previous.id, "to_user_id": successor.id})
    session.flush()
    return AccountView.model_validate(successor)


def _device_binding_view(binding, device, tenant, user) -> DeviceBindingView:
    return DeviceBindingView(
        id=binding.id,
        device_id=device.id,
        device_name=device.alias or device.name,
        device_status=device.status,
        tenant_id=tenant.id,
        tenant_name=tenant.company_name,
        user_id=user.id,
        user_display_name=user.display_name,
        login_name=user.login_name,
        binding_status=binding.status,
        login_mode="auto_login" if binding.auto_login_enabled else "password",
        expires_at=binding.expires_at,
    )


def list_device_bindings(
    session: Session,
    principal: Principal,
    *,
    tenant_id: str | None = None,
) -> list[DeviceBindingView]:
    require_super_code_machine(principal)
    query = select(DeviceUserBinding, Device, Tenant, AppUser).join(
        Device, Device.id == DeviceUserBinding.device_id,
    ).join(
        Tenant, Tenant.id == DeviceUserBinding.tenant_id,
    ).join(
        AppUser, AppUser.id == DeviceUserBinding.user_id,
    )
    if tenant_id is not None:
        query = query.where(DeviceUserBinding.tenant_id == tenant_id)
    rows = session.execute(query.order_by(DeviceUserBinding.bound_at, DeviceUserBinding.id))
    return [_device_binding_view(binding, device, tenant, user) for binding, device, tenant, user in rows]


def enroll_device_binding(session: Session, principal: Principal, payload: DeviceBindingCreate,
                          *, writer: Callable[[DeviceBindingView, str], None], request_id: str) -> DeviceBindingView:
    """Local enrollment boundary, never an HTTP handler.

    The local command opens a transaction, resolves a trusted Principal, and calls
    this service with a writer that saves the secret in the target macOS Keychain.
    The writer receives it once, after the binding and audit have flushed. On
    writer failure the caller must roll back. The result is public metadata only.
    A failed DB commit after writing can leave an unusable Keychain item; local
    enrollment must report failure and replace that item on retry.
    """
    require_super_code_machine(principal)
    device = session.scalar(select(Device).where(Device.id == payload.device_id).with_for_update())
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    if device.status != "active":
        raise HTTPException(status_code=409, detail="设备不可用")
    tenant = _tenant(session, payload.tenant_id, lock=True)
    _active_account(tenant, label="主账号")
    user = session.scalar(select(AppUser).where(AppUser.id == payload.user_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _active_account(user, label="用户")
    if user.platform_role != "super_admin":
        membership = session.scalar(select(TenantMembership).where(
            TenantMembership.user_id == user.id, TenantMembership.tenant_id == tenant.id,
            TenantMembership.status == "active",
        ))
        if membership is None:
            raise HTTPException(status_code=409, detail="用户没有该主账号的有效成员关系")
    now = datetime.now(timezone.utc)
    if payload.expires_at is not None and payload.expires_at <= now:
        raise HTTPException(status_code=422, detail="设备绑定到期时间必须晚于当前时间")
    binding = session.scalar(select(DeviceUserBinding).where(
        DeviceUserBinding.device_id == device.id, DeviceUserBinding.user_id == user.id,
        DeviceUserBinding.tenant_id == tenant.id,
    ).with_for_update())
    if binding is not None and binding.status == "active":
        raise HTTPException(status_code=409, detail="设备绑定已存在，请先撤销后重新登记")
    if payload.is_default:
        session.execute(update(DeviceUserBinding).where(DeviceUserBinding.device_id == device.id).values(is_default=False))
    secret = new_opaque_token()
    if binding is None:
        binding = DeviceUserBinding(device_id=device.id, user_id=user.id, tenant_id=tenant.id)
        session.add(binding)
    else:
        _revoke_sessions(session, AuthSession.binding_id == binding.id, reason="device_binding_reenrolled")
    binding.credential_digest = digest_token(secret)
    binding.status = "active"
    binding.auto_login_enabled = True
    binding.is_default = payload.is_default
    binding.expires_at = payload.expires_at
    binding.last_used_at = None
    binding.bound_by_user_id = principal.user_id
    binding.bound_at = now
    binding.revoked_at = None
    binding.revoke_reason = None
    session.flush()
    _audit(session, principal, event_type="device_binding_create", target_type="device_binding",
           target_id=binding.id, tenant_id=tenant.id, request_id=request_id,
           detail={"device_id": device.id, "user_id": user.id, "is_default": payload.is_default})
    session.flush()
    metadata = _device_binding_view(binding, device, tenant, user)
    try:
        writer(metadata, secret)
    except Exception:
        raise RuntimeError("本地设备登记失败，绑定事务必须回滚") from None
    return metadata


def revoke_device_binding(session: Session, principal: Principal, binding_id: str, payload: BindingRevoke,
                          *, request_id: str) -> DeviceBindingView:
    require_super_code_machine(principal)
    row = session.execute(select(DeviceUserBinding, Device, Tenant, AppUser).join(
        Device, Device.id == DeviceUserBinding.device_id,
    ).join(
        Tenant, Tenant.id == DeviceUserBinding.tenant_id,
    ).join(
        AppUser, AppUser.id == DeviceUserBinding.user_id,
    ).where(DeviceUserBinding.id == binding_id).with_for_update()).first()
    if row is None:
        raise HTTPException(status_code=404, detail="设备绑定不存在")
    binding, device, tenant, user = row
    if binding.status != "revoked":
        binding.status = "revoked"
        binding.revoked_at = datetime.now(timezone.utc)
        binding.revoke_reason = payload.reason
    binding.auto_login_enabled = False
    binding.is_default = False
    _revoke_sessions(session, AuthSession.binding_id == binding.id, reason="device_binding_revoked")
    _audit(session, principal, event_type="device_binding_revoke", target_type="device_binding",
           target_id=binding.id, tenant_id=binding.tenant_id, request_id=request_id, reason=payload.reason)
    session.flush()
    return _device_binding_view(binding, device, tenant, user)
