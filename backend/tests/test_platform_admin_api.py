import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from zhiju.app import create_app
from zhiju.auth_context import get_current_principal
from zhiju.database import get_db
from zhiju.models import (
    AppUser, AuthEvent, AuthSession, Base, Device, DeviceUserBinding,
    Permission, RolePermission, Tenant, TenantMembership,
)
from zhiju.security import digest_token, hash_password, verify_password


PASSWORD = "fixture-password-only"
TENANTS = "/api/v3/platform/tenants"
USERS = f"{TENANTS}/tenant/users"
LOCAL_USERS = "/api/v3/tenant/users"
BINDINGS = "/api/v3/platform/device-bindings"
SUPER_ADMIN = "/api/v3/platform/super-admin"


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def admin(tmp_path, password_hash):
    engine = create_engine(f"sqlite:///{tmp_path / 'platform.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    models = (AppUser, Tenant, TenantMembership, Device, Permission, RolePermission,
              AuthSession, DeviceUserBinding, AuthEvent)
    Base.metadata.create_all(engine, tables=[model.__table__ for model in models])
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        for user_id in ("super", "owner", "staff", "other-owner", "candidate"):
            db.add(AppUser(
                id=user_id, display_name=user_id, login_name=user_id,
                password_hash=password_hash, password_changed_at=now,
                platform_role="super_admin" if user_id == "super" else None,
            ))
        for device_id, trust in (("super-device", "super_code_machine"), ("device", "normal")):
            db.add(Device(id=device_id, device_key=device_id, hostname=device_id,
                          name=device_id, os_type="macos", trust_level=trust))
        db.flush()
        for tenant_id in ("tenant", "other-tenant"):
            db.add(Tenant(id=tenant_id, company_name=tenant_id, short_name=tenant_id,
                          lease_expires_at=now + timedelta(days=90)))
        db.flush()
        for user_id, tenant_id, role in (("owner", "tenant", "owner"),
                                        ("staff", "tenant", "operator"),
                                        ("other-owner", "other-tenant", "owner")):
            db.add(TenantMembership(id=f"membership-{user_id}", tenant_id=tenant_id,
                                    user_id=user_id, role_code=role))
        for user_id in ("super", "owner", "staff", "other-owner"):
            db.add(AuthSession(
                id=f"session-{user_id}", user_id=user_id,
                tenant_id="other-tenant" if user_id == "other-owner" else "tenant",
                device_id="super-device", token_digest=digest_token(f"token-{user_id}"),
                created_at=now, last_seen_at=now - timedelta(minutes=10),
                expires_at=now + timedelta(hours=8),
            ))
        db.commit()

    def open_db():
        with Session(engine, expire_on_commit=False, autoflush=False) as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = open_db
    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        client.cookies.set("zhiju_session", "token-super")
        yield SimpleNamespace(engine=engine, app=app, client=client)
    engine.dispose()


def act_as(admin, user_id):
    admin.client.cookies.set("zhiju_session", f"token-{user_id}")


def seed_successor_access(admin):
    now = datetime.now(timezone.utc)
    with Session(admin.engine) as db:
        db.add(Device(id="successor-device", device_key="successor-device", hostname="successor-device",
                      name="Successor Device", os_type="macos", trust_level="super_code_machine"))
        db.flush()
        db.add(DeviceUserBinding(
            id="successor-binding", device_id="successor-device", user_id="candidate", tenant_id="tenant",
            status="active", auto_login_enabled=True, credential_digest=digest_token("successor-device-secret"),
            bound_by_user_id="super", bound_at=now,
        ))
        db.flush()
        db.add(AuthSession(
            id="session-candidate", user_id="candidate", tenant_id=None, device_id="successor-device",
            binding_id="successor-binding", token_digest=digest_token("token-candidate"),
            status="active", created_at=now, last_seen_at=now, expires_at=now + timedelta(hours=8),
        ))
        db.commit()


def user_payload(**changes):
    return {"display_name": "New User", "login_name": "new-user", "password": PASSWORD,
            "role_code": "operator", **changes}


def tenant_payload(**changes):
    return {"company_name": "New Company", "short_name": "new-company",
            "lease_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "owner": {"display_name": "New Owner", "login_name": "new-owner", "password": PASSWORD},
            **changes}


def events(admin):
    with Session(admin.engine) as db:
        return list(db.scalars(select(AuthEvent).order_by(AuthEvent.occurred_at)))


def assert_actor(audit, event_type, target_id, *, user_id="super", tenant_id="tenant"):
    assert audit.event_type == event_type and audit.result == "success"
    assert (audit.actor_user_id, audit.actor_device_id) == (user_id, "super-device")
    assert audit.tenant_id == tenant_id and audit.target_id == target_id
    assert audit.request_id and audit.occurred_at
    assert PASSWORD not in str(audit.__dict__)


def test_tenant_create_persists_one_separate_owner_and_real_actor(admin):
    response = admin.client.post(TENANTS, json=tenant_payload())
    assert response.status_code == 201
    tenant_id = response.json()["id"]
    assert PASSWORD not in response.text and "password_hash" not in response.text
    with Session(admin.engine) as db:
        tenant = db.get(Tenant, tenant_id)
        owners = list(db.scalars(select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id, TenantMembership.role_code == "owner",
        )))
        assert len(owners) == 1 and owners[0].status == "active"
        owner = db.get(AppUser, owners[0].user_id)
        assert owner.id != tenant.id and owner.login_name == "new-owner"
        assert verify_password(PASSWORD, owner.password_hash)
        assert tenant.created_by_user_id == owner.created_by_user_id == "super"
        assert owners[0].created_by_user_id == "super" and owner.platform_role is None
    assert_actor(events(admin)[0], "tenant_create", tenant_id, tenant_id=tenant_id)
    listing = admin.client.get(TENANTS)
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()} == {"tenant", "other-tenant", tenant_id}
    assert response.headers["cache-control"] == listing.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("user_id,device_id", [("owner", "super-device"), ("super", "device")])
@pytest.mark.parametrize("method,path,payload", [
    ("post", TENANTS, tenant_payload()),
    ("patch", f"{TENANTS}/tenant", {"company_name": "Changed"}),
    ("post", f"{TENANTS}/tenant/owner", {"user_id": "staff"}),
    ("post", USERS, user_payload()),
    ("post", BINDINGS, {"device_id": "device", "user_id": "staff", "tenant_id": "tenant"}),
    ("post", f"{BINDINGS}/missing/revoke", {}),
    ("post", SUPER_ADMIN, {"user_id": "candidate"}),
])
def test_platform_writes_require_both_super_admin_and_super_device(admin, user_id, device_id,
                                                                 method, path, payload):
    with Session(admin.engine) as db:
        db.get(AuthSession, f"session-{user_id}").device_id = device_id
        db.commit()
    act_as(admin, user_id)
    response = getattr(admin.client, method)(path, json=payload)
    assert response.status_code == 403
    assert events(admin) == []


@pytest.mark.parametrize("path", [TENANTS, USERS, BINDINGS])
def test_platform_lists_require_authentication_and_dual_gate(admin, path):
    admin.client.cookies.clear()
    assert admin.client.get(path).status_code == 401
    act_as(admin, "owner")
    assert admin.client.get(path).status_code == 403


def test_duplicate_owner_login_rolls_back_entire_tenant_creation(admin):
    payload = tenant_payload()
    payload["owner"]["login_name"] = "staff"
    response = admin.client.post(TENANTS, json=payload)
    assert response.status_code == 409
    with Session(admin.engine) as db:
        assert db.scalar(select(Tenant).where(Tenant.short_name == "new-company")) is None
    assert events(admin) == []


@pytest.mark.parametrize("changes", [
    {"status": "expired"}, {"company_name": "   "}, {"lease_expires_at": "invalid"},
    {"lease_expires_at": "2030-01-01T00:00:00"}, {"lease_expires_at": "2000-01-01T00:00:00Z"},
    {"owner": {"display_name": "New", "login_name": "new", "password": ""}},
])
def test_tenant_creation_rejects_invalid_status_lease_and_owner(admin, changes):
    response = admin.client.post(TENANTS, json=tenant_payload(**changes))
    assert response.status_code == 422
    assert events(admin) == []


def test_tenant_update_revokes_its_sessions_on_suspension_and_audits_actor(admin):
    response = admin.client.patch(f"{TENANTS}/tenant", json={"status": "suspended",
                                                          "suspended_reason": "Lease review"})
    assert response.status_code == 200
    with Session(admin.engine) as db:
        tenant = db.get(Tenant, "tenant")
        assert tenant.status == "suspended" and tenant.suspended_at is not None
        assert tenant.suspended_reason == "Lease review"
        assert db.get(AuthSession, "session-staff").status == "revoked"
        assert db.get(AuthSession, "session-other-owner").status == "active"
    assert_actor(events(admin)[0], "tenant_update", "tenant")


@pytest.mark.parametrize("path,field", [
    (f"{TENANTS}/tenant", "lease_expires_at"), (f"{TENANTS}/tenant", "status"),
    (f"{TENANTS}/tenant", "company_name"), (f"{TENANTS}/tenant", "short_name"),
    (f"{USERS}/staff", "display_name"), (f"{USERS}/staff", "login_name"),
    (f"{USERS}/staff", "status"), (f"{USERS}/staff", "role_code"),
    (f"{USERS}/staff", "membership_status"),
])
def test_patch_rejects_null_for_required_identity_fields_without_writes(admin, path, field):
    with TestClient(admin.app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}) as client:
        client.cookies.set("zhiju_session", "token-super")
        response = client.patch(path, json={field: None})
    assert response.status_code == 422
    assert events(admin) == []


def test_owner_transfer_preserves_exactly_one_owner_and_audits_both_users(admin):
    response = admin.client.post(f"{TENANTS}/tenant/owner", json={"user_id": "staff"})
    assert response.status_code == 200
    with Session(admin.engine) as db:
        memberships = list(db.scalars(select(TenantMembership).where(TenantMembership.tenant_id == "tenant")))
        assert {m.user_id: m.role_code for m in memberships} == {"owner": "admin", "staff": "owner"}
        assert all(m.status == "active" for m in memberships)
    audit = events(admin)[0]
    assert_actor(audit, "owner_transfer", "tenant")
    assert '"from_user_id": "owner"' in audit.detail and '"to_user_id": "staff"' in audit.detail


@pytest.mark.parametrize("changes", [{"role_code": "owner"}, {"role_code": "super_admin"},
                                    {"platform_role": "super_admin"}, {"status": "expired"}])
def test_user_creation_rejects_extra_owner_platform_role_and_invalid_status(admin, changes):
    response = admin.client.post(USERS, json=user_payload(**changes))
    assert response.status_code == 422
    assert events(admin) == []


def test_tenant_owner_manages_regular_roles_with_global_unique_login(admin):
    act_as(admin, "owner")
    for role in ("admin", "operator", "viewer"):
        response = admin.client.post(LOCAL_USERS, json=user_payload(login_name=f"new-{role}", role_code=role))
        assert response.status_code == 201
        assert response.json()["role_code"] == role and response.json()["tenant_id"] == "tenant"
        assert "password_hash" not in response.text and PASSWORD not in response.text
        assert_actor(events(admin)[-1], "user_create", response.json()["id"], user_id="owner")
    duplicate = admin.client.post(LOCAL_USERS, json=user_payload(login_name="other-owner"))
    assert duplicate.status_code == 409
    listing = admin.client.get(LOCAL_USERS)
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()}.isdisjoint({"super", "other-owner"})
    changed = admin.client.patch(f"{LOCAL_USERS}/staff", json={"role_code": "viewer", "display_name": "Read Only"})
    assert changed.status_code == 200 and changed.json()["role_code"] == "viewer"
    assert_actor(events(admin)[-1], "user_update", "staff", user_id="owner")


@pytest.mark.parametrize("user_id", ["staff", "super"])
def test_tenant_user_administration_requires_actual_owner_membership(admin, user_id):
    act_as(admin, user_id)
    assert admin.client.get(LOCAL_USERS).status_code == 403
    assert admin.client.post(LOCAL_USERS, json=user_payload()).status_code == 403
    assert events(admin) == []


@pytest.mark.parametrize("user_id,changes,want", [
    ("other-owner", {"display_name": "Changed"}, 404),
    ("owner", {"status": "suspended"}, 403),
    ("owner", {"role_code": "viewer"}, 403),
    ("staff", {"platform_role": "super_admin"}, 422),
    ("staff", {"role_code": "owner"}, 422),
])
def test_tenant_owner_cannot_cross_tenants_modify_owner_or_platform_role(admin, user_id, changes, want):
    act_as(admin, "owner")
    assert admin.client.get(LOCAL_USERS).status_code == 200
    response = admin.client.patch(f"{LOCAL_USERS}/{user_id}", json=changes)
    assert response.status_code == want
    assert events(admin) == []


def test_owner_membership_cannot_be_removed_through_user_patch(admin):
    response = admin.client.patch(f"{USERS}/owner", json={"membership_status": "suspended"})
    assert response.status_code == 409
    response = admin.client.patch(f"{USERS}/owner", json={"role_code": "admin"})
    assert response.status_code == 409
    with Session(admin.engine) as db:
        assert db.get(TenantMembership, "membership-owner").role_code == "owner"
    assert events(admin) == []


@pytest.mark.parametrize("changes", [{"status": "suspended"},
                                    {"lease_expires_at": "2000-01-01T00:00:00Z"}])
def test_user_suspension_or_explicit_expiration_revokes_all_user_sessions(admin, changes):
    response = admin.client.patch(f"{USERS}/staff", json=changes)
    assert response.status_code == 200
    with Session(admin.engine) as db:
        assert db.get(AuthSession, "session-staff").status == "revoked"
        assert db.get(AuthSession, "session-owner").status == "active"


@pytest.mark.parametrize("path,actor", [(USERS, "super"), (LOCAL_USERS, "owner")])
def test_password_reset_revokes_all_target_sessions_and_clears_lockout(admin, path, actor):
    now = datetime.now(timezone.utc)
    with Session(admin.engine) as db:
        staff = db.get(AppUser, "staff")
        staff.failed_login_count = 5
        staff.locked_until = now + timedelta(minutes=15)
        db.add(AuthSession(id="second-staff", user_id="staff", tenant_id="other-tenant",
                           token_digest=digest_token("second-staff"), created_at=now,
                           last_seen_at=now, expires_at=now + timedelta(hours=8)))
        db.commit()
    act_as(admin, actor)
    response = admin.client.post(f"{path}/staff/password", json={"password": "new-password-marker"})
    assert response.status_code == 200
    assert "new-password-marker" not in response.text
    with Session(admin.engine) as db:
        staff = db.get(AppUser, "staff")
        assert verify_password("new-password-marker", staff.password_hash)
        assert utc(staff.password_changed_at) >= now
        assert staff.failed_login_count == 0 and staff.locked_until is None
        assert {item.status for item in db.scalars(select(AuthSession).where(AuthSession.user_id == "staff"))} == {"revoked"}
        assert db.get(AuthSession, "session-owner").status == "active"
    assert_actor(events(admin)[0], "password_reset", "staff", user_id=actor)
    assert "new-password-marker" not in str(events(admin)[0].__dict__)


def test_tenant_owner_cannot_change_global_account_fields_of_shared_user(admin):
    with Session(admin.engine) as db:
        db.add(TenantMembership(user_id="staff", tenant_id="other-tenant", role_code="viewer"))
        db.commit()
    act_as(admin, "owner")
    assert admin.client.patch(f"{LOCAL_USERS}/staff", json={"login_name": "changed"}).status_code == 403
    assert admin.client.post(f"{LOCAL_USERS}/staff/password", json={"password": "changed"}).status_code == 403
    assert admin.client.patch(f"{LOCAL_USERS}/staff", json={"role_code": "viewer"}).status_code == 200


@pytest.mark.parametrize("path,payload", [
    (TENANTS, {"owner": {"password": "password-marker"}}),
    (USERS, {"password": ["password-marker"]}),
    (f"{USERS}/staff/password", {"password": ["password-marker"]}),
    (LOCAL_USERS, [{"password": "password-marker"}]),
    (SUPER_ADMIN, {"new_user": {"password": "password-marker"}}),
])
def test_admin_validation_errors_never_echo_password_or_raw_input(admin, path, payload):
    response = admin.client.post(path, json=payload)
    assert response.status_code == 422
    assert "password-marker" not in response.text and '"input"' not in response.text


@pytest.mark.parametrize("origin", [None, "http://other-origin"])
def test_administration_write_rejects_missing_or_wrong_origin(admin, origin):
    with TestClient(admin.app) as client:
        client.cookies.set("zhiju_session", "token-super")
        response = client.post(TENANTS, json=tenant_payload(), headers={"Origin": origin} if origin else {})
    assert response.status_code == 403 and events(admin) == []


@pytest.mark.parametrize("operation", ["create", "owner", "password", "super"])
def test_audit_failure_rolls_back_entire_admin_transaction_including_stale_heartbeat(admin, operation):
    if operation == "super":
        seed_successor_access(admin)

    def reject_audit(mapper, connection, target):
        raise RuntimeError("test audit unavailable")

    event.listen(AuthEvent, "before_insert", reject_audit)
    try:
        with TestClient(admin.app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}) as client:
            client.cookies.set("zhiju_session", "token-super")
            if operation == "create":
                response = client.post(TENANTS, json=tenant_payload())
            elif operation == "owner":
                response = client.post(f"{TENANTS}/tenant/owner", json={"user_id": "staff"})
            elif operation == "password":
                response = client.post(f"{USERS}/staff/password", json={"password": "changed"})
            else:
                response = client.post(SUPER_ADMIN, json={"user_id": "candidate"})
        assert response.status_code == 500
    finally:
        event.remove(AuthEvent, "before_insert", reject_audit)
    with Session(admin.engine) as db:
        assert db.scalar(select(Tenant).where(Tenant.short_name == "new-company")) is None
        assert db.get(TenantMembership, "membership-owner").role_code == "owner"
        assert db.get(TenantMembership, "membership-staff").role_code == "operator"
        assert verify_password(PASSWORD, db.get(AppUser, "staff").password_hash)
        assert db.get(AuthSession, "session-staff").status == "active"
        assert db.get(AuthSession, "session-super").status == "active"
        assert db.get(AppUser, "super").platform_role == "super_admin"
        assert db.get(AppUser, "candidate").platform_role is None
        assert utc(db.get(AuthSession, "session-super").last_seen_at) < datetime.now(timezone.utc) - timedelta(minutes=5)
    assert events(admin) == []


def test_super_admin_transfer_is_atomic_unique_and_revokes_previous_super_sessions(admin):
    seed_successor_access(admin)
    response = admin.client.post(SUPER_ADMIN, json={"user_id": "candidate"})
    assert response.status_code == 200
    target_id = response.json()["id"]
    with Session(admin.engine) as db:
        assert [item.id for item in db.scalars(select(AppUser).where(AppUser.platform_role == "super_admin"))] == [target_id]
        assert db.get(AppUser, "super").platform_role is None
        assert db.get(AuthSession, "session-super").status == "revoked"
        assert db.scalar(select(TenantMembership).where(TenantMembership.user_id == target_id)) is None
    assert_actor(events(admin)[0], "super_admin_transfer", target_id, tenant_id=None)
    assert PASSWORD not in response.text and "password_hash" not in response.text
    assert admin.client.get(TENANTS).status_code == 401
    act_as(admin, "candidate")
    assert admin.client.get(TENANTS).status_code == 200


@pytest.mark.parametrize("unavailable", [
    "missing_session", "missing_binding", "revoked_session", "expired_session",
    "revoked_binding", "suspended_binding", "auto_login_disabled", "expired_binding",
    "normal_device", "inactive_device", "wrong_device", "wrong_user", "inactive_session_tenant",
])
def test_super_admin_transfer_refuses_successor_without_usable_trusted_session(admin, unavailable):
    if unavailable != "missing_session":
        seed_successor_access(admin)
        with Session(admin.engine) as db:
            auth_session = db.get(AuthSession, "session-candidate")
            binding = db.get(DeviceUserBinding, "successor-binding")
            device = db.get(Device, "successor-device")
            if unavailable == "missing_binding":
                auth_session.binding_id = None
            elif unavailable == "revoked_session":
                auth_session.status = "revoked"
            elif unavailable == "expired_session":
                auth_session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            elif unavailable == "revoked_binding":
                binding.status = "revoked"
            elif unavailable == "suspended_binding":
                binding.status = "suspended"
            elif unavailable == "auto_login_disabled":
                binding.auto_login_enabled = False
            elif unavailable == "expired_binding":
                binding.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            elif unavailable == "normal_device":
                device.trust_level = "normal"
            elif unavailable == "inactive_device":
                device.status = "inactive"
            elif unavailable == "wrong_device":
                auth_session.device_id = "super-device"
            elif unavailable == "wrong_user":
                binding.user_id = "owner"
            else:
                auth_session.tenant_id = "other-tenant"
                db.get(Tenant, "other-tenant").status = "suspended"
            db.commit()
    response = admin.client.post(SUPER_ADMIN, json={"user_id": "candidate"})
    assert response.status_code == 409 and events(admin) == []
    with Session(admin.engine) as db:
        assert db.get(AppUser, "super").platform_role == "super_admin"
        assert db.get(AppUser, "candidate").platform_role is None
        assert db.get(AuthSession, "session-super").status == "active"
    assert admin.client.get(TENANTS).status_code == 200


def test_super_admin_transfer_refuses_new_account_without_creating_it_or_revoking_actor(admin):
    response = admin.client.post(SUPER_ADMIN, json={"new_user": {
        "display_name": "Successor", "login_name": "successor", "password": PASSWORD,
    }})
    assert response.status_code == 409 and events(admin) == []
    with Session(admin.engine) as db:
        assert db.scalar(select(AppUser).where(AppUser.login_name == "successor")) is None
        assert db.get(AppUser, "super").platform_role == "super_admin"
        assert db.get(AuthSession, "session-super").status == "active"


@pytest.mark.parametrize("payload,want", [
    ({"user_id": "owner"}, 409), ({"user_id": "super"}, 409),
    ({"user_id": "candidate", "new_user": {"display_name": "x", "login_name": "x", "password": PASSWORD}}, 422),
    ({}, 422),
])
def test_super_admin_transfer_rejects_tenant_member_self_or_ambiguous_target(admin, payload, want):
    response = admin.client.post(SUPER_ADMIN, json=payload)
    assert response.status_code == want and events(admin) == []
    with Session(admin.engine) as db:
        assert [item.id for item in db.scalars(select(AppUser).where(AppUser.platform_role == "super_admin"))] == ["super"]


def test_http_binding_creation_explains_local_enrollment_boundary_without_creating_unusable_binding(admin):
    response = admin.client.post(BINDINGS, json={"device_id": "device", "user_id": "staff", "tenant_id": "tenant"})
    assert response.status_code == 409
    assert "本地" in response.json()["detail"] and "Keychain" in response.json()["detail"]
    with Session(admin.engine) as db:
        assert list(db.scalars(select(DeviceUserBinding))) == []
    assert events(admin) == []


def enroll(admin, writer, *, actor="super", **changes):
    from zhiju.schemas.platform_admin import DeviceBindingCreate
    from zhiju.services.platform_admin import enroll_device_binding

    request = Request({"type": "http", "headers": [(b"cookie", f"zhiju_session=token-{actor}".encode())]})
    with Session(admin.engine, expire_on_commit=False, autoflush=False) as db:
        with db.begin():
            principal = get_current_principal(request, db)
            return enroll_device_binding(
                db, principal, DeviceBindingCreate(**{"device_id": "device", "user_id": "staff", "tenant_id": "tenant", **changes}),
                writer=writer, request_id="local-enrollment-test",
            )


def test_local_binding_enrollment_delivers_secret_once_to_writer_and_only_persists_digest(admin):
    assert admin.client.get(BINDINGS).status_code == 200
    written = []
    result = enroll(admin, lambda binding, secret: written.append((binding, secret)), is_default=True)
    assert len(written) == 1
    metadata, secret = written[0]
    assert result.id == metadata.id and len(secret) >= 43
    with Session(admin.engine) as db:
        binding = db.get(DeviceUserBinding, result.id)
        assert binding.credential_digest == hashlib.sha256(secret.encode()).hexdigest()
        assert binding.status == "active" and binding.is_default
        assert binding.bound_by_user_id == "super" and binding.auto_login_enabled
        assert secret not in str(binding.__dict__)
    listing = admin.client.get(BINDINGS)
    assert listing.status_code == 200 and listing.json()[0]["id"] == result.id
    assert secret not in listing.text and "credential_digest" not in listing.text
    assert secret not in str(result) and secret not in str(metadata)
    assert_actor(events(admin)[0], "device_binding_create", result.id)
    assert secret not in str(events(admin)[0].__dict__)


def test_failed_local_writer_rolls_back_binding_and_audit(admin):
    assert admin.client.get(BINDINGS).status_code == 200

    def failed_writer(binding, secret):
        raise RuntimeError(f"writer rejected {secret}")

    with pytest.raises(RuntimeError, match="本地设备登记失败") as caught:
        enroll(admin, failed_writer)
    assert "writer rejected" not in str(caught.value)
    with Session(admin.engine) as db:
        assert list(db.scalars(select(DeviceUserBinding))) == []
    assert events(admin) == []


@pytest.mark.parametrize("actor,device_id", [("owner", "super-device"), ("super", "device")])
def test_local_enrollment_service_enforces_dual_gate_before_calling_writer(admin, actor, device_id):
    with Session(admin.engine) as db:
        db.get(AuthSession, f"session-{actor}").device_id = device_id
        db.commit()
    delivered = []
    with pytest.raises(HTTPException) as caught:
        enroll(admin, lambda binding, secret: delivered.append(secret), actor=actor)
    assert caught.value.status_code == 403 and delivered == [] and events(admin) == []


@pytest.mark.parametrize("model,identity,field,value", [
    (Device, "device", "status", "inactive"),
    (AppUser, "staff", "status", "suspended"),
    (AppUser, "staff", "lease_expires_at", datetime(2000, 1, 1, tzinfo=timezone.utc)),
    (Tenant, "other-tenant", "status", "suspended"),
    (Tenant, "other-tenant", "lease_expires_at", datetime(2000, 1, 1, tzinfo=timezone.utc)),
    (TenantMembership, "membership-staff", "status", "suspended"),
])
def test_local_enrollment_rejects_unavailable_target_before_delivering_secret(admin, model, identity, field, value):
    with Session(admin.engine) as db:
        setattr(db.get(model, identity), field, value)
        db.commit()
    delivered = []
    changes = {"tenant_id": "other-tenant", "user_id": "other-owner"} if model is Tenant else {}
    with pytest.raises(HTTPException) as caught:
        enroll(admin, lambda binding, secret: delivered.append(secret), **changes)
    assert caught.value.status_code == 409 and delivered == [] and events(admin) == []


def test_local_enrollment_keeps_one_default_and_reenrolls_revoked_scope_with_new_secret(admin):
    delivered = []
    writer = lambda binding, secret: delivered.append(secret)
    first = enroll(admin, writer, is_default=True)
    second = enroll(admin, writer, is_default=True, user_id="owner")
    with Session(admin.engine) as db:
        assert not db.get(DeviceUserBinding, first.id).is_default
        assert db.get(DeviceUserBinding, second.id).is_default
    with pytest.raises(HTTPException) as caught:
        enroll(admin, writer, user_id="owner")
    assert caught.value.status_code == 409 and len(delivered) == 2
    assert admin.client.post(f"{BINDINGS}/{first.id}/revoke", json={}).status_code == 200
    replacement = enroll(admin, writer, is_default=True)
    assert replacement.id == first.id and len(delivered) == 3 and delivered[0] != delivered[2]
    with Session(admin.engine) as db:
        assert db.get(DeviceUserBinding, first.id).credential_digest == hashlib.sha256(delivered[2].encode()).hexdigest()
        assert not db.get(DeviceUserBinding, second.id).is_default


def test_enrollment_audit_failure_rolls_back_default_changes_and_never_calls_writer(admin):
    initial = enroll(admin, lambda binding, secret: None, is_default=True)
    delivered = []

    def reject_audit(mapper, connection, target):
        raise RuntimeError("test audit unavailable")

    event.listen(AuthEvent, "before_insert", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="test audit unavailable"):
            enroll(admin, lambda binding, secret: delivered.append(secret), is_default=True, user_id="owner")
    finally:
        event.remove(AuthEvent, "before_insert", reject_audit)
    assert delivered == []
    with Session(admin.engine) as db:
        bindings = list(db.scalars(select(DeviceUserBinding)))
        assert len(bindings) == 1 and bindings[0].id == initial.id and bindings[0].is_default


def test_binding_revocation_revokes_original_binding_sessions_even_after_tenant_switch(admin):
    assert admin.client.get(BINDINGS).status_code == 200
    binding = enroll(admin, lambda binding, secret: None)
    with Session(admin.engine) as db:
        auth_session = db.get(AuthSession, "session-staff")
        auth_session.binding_id = binding.id
        auth_session.tenant_id = "other-tenant"
        db.commit()
    response = admin.client.post(f"{BINDINGS}/{binding.id}/revoke", json={"reason": "Device retired"})
    assert response.status_code == 200
    with Session(admin.engine) as db:
        stored = db.get(DeviceUserBinding, binding.id)
        assert stored.status == "revoked" and not stored.auto_login_enabled
        assert stored.revoked_at is not None and stored.revoke_reason == "Device retired"
        assert db.get(AuthSession, "session-staff").status == "revoked"
        assert db.get(AuthSession, "session-owner").status == "active"
    assert_actor(events(admin)[-1], "device_binding_revoke", binding.id)


def test_auth_administration_does_not_broadcast_to_global_business_sse(admin, monkeypatch):
    async def unexpected_broadcast(change):
        pytest.fail("Auth administration must not enter the unscoped business SSE channel")

    monkeypatch.setattr("zhiju.app.publish_change_event", unexpected_broadcast)
    response = admin.client.post(TENANTS, json=tenant_payload())
    assert response.status_code == 201


@pytest.mark.parametrize("offset_hours", [8, -7])
@pytest.mark.parametrize("target", ["tenant_create", "owner_create", "user_create",
                                    "tenant_patch", "user_patch", "binding_create"])
def test_offset_leases_preserve_utc_instant_through_storage_and_api_round_trip(admin, offset_hours, target):
    expected = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0)
    supplied = expected.astimezone(timezone(timedelta(hours=offset_hours))).isoformat()
    if target == "tenant_create":
        response = admin.client.post(TENANTS, json=tenant_payload(lease_expires_at=supplied))
        assert response.status_code == 201
        identity, model, field, list_path = response.json()["id"], Tenant, "lease_expires_at", TENANTS
    elif target == "owner_create":
        payload = tenant_payload()
        payload["owner"]["lease_expires_at"] = supplied
        response = admin.client.post(TENANTS, json=payload)
        assert response.status_code == 201
        list_path = f"{TENANTS}/{response.json()['id']}/users"
        response = admin.client.get(list_path)
        assert response.status_code == 200
        identity, model, field = response.json()[0]["id"], AppUser, "lease_expires_at"
    elif target == "user_create":
        response = admin.client.post(USERS, json=user_payload(lease_expires_at=supplied))
        assert response.status_code == 201
        identity, model, field, list_path = response.json()["id"], AppUser, "lease_expires_at", USERS
    elif target == "tenant_patch":
        response = admin.client.patch(f"{TENANTS}/other-tenant", json={"lease_expires_at": supplied})
        assert response.status_code == 200
        identity, model, field, list_path = "other-tenant", Tenant, "lease_expires_at", TENANTS
    elif target == "user_patch":
        response = admin.client.patch(f"{USERS}/staff", json={"lease_expires_at": supplied})
        assert response.status_code == 200
        identity, model, field, list_path = "staff", AppUser, "lease_expires_at", USERS
    else:
        binding = enroll(admin, lambda metadata, secret: None, expires_at=supplied)
        identity, model, field, list_path = binding.id, DeviceUserBinding, "expires_at", BINDINGS
    with Session(admin.engine) as db:
        assert utc(getattr(db.get(model, identity), field)) == expected
    listing = admin.client.get(list_path)
    assert listing.status_code == 200
    actual = next(item for item in listing.json() if item["id"] == identity)[field]
    returned_instant = datetime.fromisoformat(actual)
    assert returned_instant.utcoffset() == timedelta(0)
    assert returned_instant == expected


@pytest.mark.parametrize("target", ["tenant", "user"])
@pytest.mark.parametrize("offset_hours,expires_in_hours,want", [(8, -1, 401), (-7, 1, 200)])
def test_offset_lease_enforces_real_expiration_after_patch_and_new_login(admin, target,
                                                                      offset_hours, expires_in_hours, want):
    expires = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
    supplied = expires.astimezone(timezone(timedelta(hours=offset_hours))).isoformat()
    path, login_name = (f"{TENANTS}/other-tenant", "other-owner") if target == "tenant" else (f"{USERS}/staff", "staff")
    response = admin.client.patch(path, json={"lease_expires_at": supplied})
    assert response.status_code == 200
    response = admin.client.post("/api/v3/auth/login", json={"login_name": login_name, "password": PASSWORD})
    assert response.status_code == want
