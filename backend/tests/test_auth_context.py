from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from zhiju import auth_context
from zhiju.auth_context import Principal, get_current_principal, get_optional_principal
from zhiju.database import get_db
from zhiju.models import (
    AppUser, AuthSession, Base, Device, Permission, RolePermission, Tenant, TenantMembership,
)
from zhiju.permissions import require_permission, require_super_code_machine
from zhiju.security import digest_token


NOW = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)
TOKEN = "local-test-session-token"


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def request(token=TOKEN, extra_headers=()):
    headers = list(extra_headers)
    if token is not None:
        headers.append((b"cookie", f"zhiju_session={token}".encode()))
    return Request({"type": "http", "headers": headers})


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_context, "datetime", FrozenDatetime)
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    tables = [model.__table__ for model in (
        AppUser, Tenant, TenantMembership, Device, Permission, RolePermission, AuthSession,
    )]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as db:
        user = AppUser(id="user", display_name="Owner", login_name="owner", password_hash="unused",
                       password_changed_at=NOW, status="active")
        tenant = Tenant(id="tenant", company_name="Company", short_name="company", status="active",
                        lease_expires_at=NOW + timedelta(days=30))
        device = Device(id="device", device_key="test-device", name="Device", hostname="test-host",
                        os_type="macos", status="active", trust_level="normal")
        membership = TenantMembership(id="membership", user_id="user", tenant_id="tenant",
                                      role_code="owner", status="active")
        auth_session = AuthSession(id="session", user_id="user", tenant_id="tenant", device_id="device",
                                   token_digest=digest_token(TOKEN), status="active", created_at=NOW,
                                   expires_at=NOW + timedelta(hours=8), last_seen_at=NOW)
        db.add_all([user, tenant, device, membership, auth_session])
        for code, roles in [
            ("channel.read", ["owner", "viewer", "super_admin"]),
            ("channel.manage", ["owner", "super_admin"]),
            ("platform.tenant.manage", ["super_admin"]),
        ]:
            db.add(Permission(id=code, code=code, name_zh=code))
            db.add_all(RolePermission(role_code=role, permission_id=code) for role in roles)
        db.commit()
        yield SimpleNamespace(db=db, engine=engine, user=user, tenant=tenant, device=device,
                              membership=membership, auth_session=auth_session)
    engine.dispose()


def expect_status(context, status, req=None):
    with pytest.raises(HTTPException) as exc:
        get_current_principal(req or request(), context.db)
    assert exc.value.status_code == status


def test_active_session_resolves_real_actor_current_tenant_and_role_permissions(context):
    principal = get_current_principal(request(), context.db)
    assert principal == Principal(
        user_id="user", tenant_id="tenant", membership_role="owner", platform_role=None,
        device_id="device", device_trust_level="normal",
        permissions=frozenset({"channel.read", "channel.manage"}),
    )
    assert require_permission("channel.manage")(principal) is principal


@pytest.mark.parametrize("token", [None, "", "unknown-token"])
def test_missing_or_unknown_session_is_optional_but_current_requires_login(context, token):
    assert get_optional_principal(request(token), context.db) is None
    expect_status(context, 401, request(token))


@pytest.mark.parametrize("status", ["revoked", "expired"])
def test_inactive_session_is_rejected(context, status):
    context.auth_session.status = status
    context.db.commit()
    expect_status(context, 401)


@pytest.mark.parametrize("offset", [-1, 0])
def test_session_expiration_including_exact_boundary_is_rejected(context, offset):
    context.auth_session.expires_at = NOW + timedelta(seconds=offset)
    context.db.commit()
    expect_status(context, 401)


def test_suspended_user_is_rejected(context):
    context.user.status = "suspended"
    context.db.commit()
    expect_status(context, 401)


@pytest.mark.parametrize("offset", [-1, 0])
def test_expired_user_lease_is_rejected(context, offset):
    context.user.lease_expires_at = NOW + timedelta(seconds=offset)
    context.db.commit()
    expect_status(context, 401)


@pytest.mark.parametrize("reason", ["suspended", "expired", "boundary"])
def test_unavailable_tenant_is_forbidden(context, reason):
    if reason == "suspended":
        context.tenant.status = "suspended"
    else:
        context.tenant.lease_expires_at = NOW - timedelta(seconds=reason == "expired")
    context.db.commit()
    expect_status(context, 403)


@pytest.mark.parametrize("reason", ["missing", "suspended", "other_tenant", "no_tenant"])
def test_normal_user_requires_active_membership_in_current_tenant(context, reason):
    if reason == "missing":
        context.db.delete(context.membership)
    elif reason == "suspended":
        context.membership.status = "suspended"
    elif reason == "other_tenant":
        context.db.add(Tenant(id="other", company_name="Other", short_name="other",
                              lease_expires_at=NOW + timedelta(days=10)))
        context.auth_session.tenant_id = "other"
    else:
        context.auth_session.tenant_id = None
    context.db.commit()
    expect_status(context, 403)


def test_viewer_can_read_but_cannot_write_or_match_permission_prefix(context):
    context.membership.role_code = "viewer"
    context.db.commit()
    principal = get_current_principal(request(), context.db)
    assert require_permission("channel.read")(principal) is principal
    for code in ("channel.manage", "channel", "channel.*"):
        with pytest.raises(HTTPException) as exc:
            require_permission(code)(principal)
        assert exc.value.status_code == 403


@pytest.mark.parametrize("platform_role,trust_level,allowed", [
    (None, "super_code_machine", False),
    ("super_admin", "normal", False),
    ("super_admin", "code_machine", False),
    ("super_admin", "production_device", False),
    ("super_admin", "super_code_machine", True),
])
def test_super_gate_requires_both_user_role_and_device_trust(context, platform_role, trust_level, allowed):
    context.user.platform_role = platform_role
    context.device.trust_level = trust_level
    context.db.commit()
    principal = get_current_principal(request(), context.db)
    assert ("platform.tenant.manage" in principal.permissions) == (platform_role == "super_admin")
    if allowed:
        assert require_super_code_machine(principal) is principal
    else:
        with pytest.raises(HTTPException) as exc:
            require_super_code_machine(principal)
        assert exc.value.status_code == 403


@pytest.mark.parametrize("tenant_id", [None, "tenant"])
def test_super_admin_without_membership_keeps_real_actor_and_platform_permissions(context, tenant_id):
    context.user.platform_role = "super_admin"
    context.auth_session.tenant_id = tenant_id
    context.db.delete(context.membership)
    context.db.commit()
    principal = get_current_principal(request(), context.db)
    assert principal.user_id == "user"
    assert principal.tenant_id == tenant_id
    assert principal.membership_role is None
    assert "platform.tenant.manage" in principal.permissions


def test_super_admin_current_tenant_must_still_be_active(context):
    context.user.platform_role = "super_admin"
    context.tenant.status = "suspended"
    context.db.commit()
    expect_status(context, 403)


@pytest.mark.parametrize("device_status", [None, "inactive", "retired"])
def test_unavailable_device_cannot_supply_super_machine_trust(context, device_status):
    context.user.platform_role = "super_admin"
    context.device.trust_level = "super_code_machine"
    if device_status is None:
        context.auth_session.device_id = None
    else:
        context.device.status = device_status
    context.db.commit()
    principal = get_current_principal(request(), context.db)
    assert principal.device_trust_level == "normal"
    with pytest.raises(HTTPException) as exc:
        require_super_code_machine(principal)
    assert exc.value.status_code == 403


def test_headers_cannot_supply_or_override_identity_device_tenant_or_permissions(context):
    headers = [
        (b"x-user-id", b"admin"), (b"x-device-id", b"super-machine"),
        (b"x-tenant-id", b"other"), (b"x-platform-role", b"super_admin"),
        (b"x-permissions", b"platform.tenant.manage"),
        (b"x-device-trust-level", b"super_code_machine"),
        (b"authorization", b"Bearer not-a-session-cookie"),
    ]
    assert get_optional_principal(request(None, headers), context.db) is None
    principal = get_current_principal(request(extra_headers=headers), context.db)
    assert (principal.user_id, principal.device_id, principal.tenant_id) == ("user", "device", "tenant")
    assert principal.platform_role is None
    assert principal.device_trust_level == "normal"
    assert "platform.tenant.manage" not in principal.permissions


@pytest.mark.parametrize("age_seconds,updated", [(299, False), (300, True), (600, True)])
def test_last_seen_persists_at_most_once_per_five_minutes(context, age_seconds, updated):
    previous = NOW - timedelta(seconds=age_seconds)
    context.auth_session.last_seen_at = previous
    context.db.commit()
    get_current_principal(request(), context.db)
    with Session(context.engine) as independent:
        stored = independent.get(AuthSession, "session").last_seen_at
    expected = NOW if updated else previous
    assert stored == expected.replace(tzinfo=None)


def test_dependencies_work_through_fastapi_and_cookie_auth(context):
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: context.db

    @app.get("/write")
    def write(principal: Principal = Depends(require_permission("channel.manage"))):
        return {"user_id": principal.user_id}

    @app.get("/super")
    def super_action(principal: Principal = Depends(require_super_code_machine)):
        return {"user_id": principal.user_id}

    with TestClient(app) as client:
        assert client.get("/write").status_code == 401
        client.cookies.set("zhiju_session", TOKEN)
        assert client.get("/write").json() == {"user_id": "user"}
        assert client.get("/super").status_code == 403
