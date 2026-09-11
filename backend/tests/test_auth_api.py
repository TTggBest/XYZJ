import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from zhiju.app import create_app
from zhiju.config import get_settings
from zhiju.database import get_db
from zhiju.models import (
    AppUser, AuthEvent, AuthSession, Base, Device, DeviceUserBinding,
    Permission, RolePermission, Tenant, TenantMembership,
)
from zhiju.security import digest_token, hash_password


PASSWORD = "correct horse battery staple"
CURRENT_TOKEN = "current-test-session"
OTHER_TOKEN = "other-test-session"
LOGIN = "/api/v3/auth/login"
LOGOUT = "/api/v3/auth/logout"
ME = "/api/v3/auth/me"
SWITCH = "/api/v3/auth/switch-tenant"


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def auth(tmp_path, password_hash):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    models = (
        AppUser, Tenant, TenantMembership, Device, Permission, RolePermission,
        AuthSession, DeviceUserBinding, AuthEvent,
    )
    Base.metadata.create_all(engine, tables=[model.__table__ for model in models])
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([
            AppUser(id="user", display_name="Owner", login_name="owner",
                    password_hash=password_hash, password_changed_at=now),
            Tenant(id="tenant", company_name="First Company", short_name="first",
                   lease_expires_at=now + timedelta(days=30)),
            Tenant(id="other-tenant", company_name="Other Company", short_name="other",
                   lease_expires_at=now + timedelta(days=30)),
            Device(id="device", device_key="local-fixture", name="Fixture Device",
                   alias="Workstation", hostname="fixture-host", os_type="macos",
                   trust_level="normal"),
        ])
        db.flush()
        db.add(TenantMembership(id="membership", user_id="user", tenant_id="tenant",
                                role_code="owner"))
        for code, roles in [
            ("channel.read", ["owner", "super_admin"]),
            ("channel.manage", ["owner", "super_admin"]),
            ("platform.tenant.manage", ["super_admin"]),
        ]:
            db.add(Permission(id=code, code=code, name_zh=code))
            db.flush()
            db.add_all(RolePermission(role_code=role, permission_id=code) for role in roles)
        db.commit()

    def open_db():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    settings = SimpleNamespace(env="development")
    app = create_app()
    app.dependency_overrides[get_db] = open_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        yield SimpleNamespace(engine=engine, app=app, client=client, settings=settings)
    engine.dispose()


def login(auth, **overrides):
    return auth.client.post(LOGIN, json={"login_name": "owner", "password": PASSWORD, **overrides})


def seed_sessions(auth, *, super_admin=False, age_minutes=0):
    now = datetime.now(timezone.utc)
    with Session(auth.engine) as db:
        if super_admin:
            db.get(AppUser, "user").platform_role = "super_admin"
            db.delete(db.get(TenantMembership, "membership"))
        for session_id, token in [("current", CURRENT_TOKEN), ("other", OTHER_TOKEN)]:
            db.add(AuthSession(
                id=session_id, user_id="user", tenant_id="tenant", device_id="device",
                token_digest=digest_token(token), created_at=now,
                last_seen_at=now - timedelta(minutes=age_minutes),
                expires_at=now + timedelta(hours=8),
            ))
        for binding_id, tenant_id in [("binding", "tenant"), ("other-binding", "other-tenant")]:
            db.add(DeviceUserBinding(
                id=binding_id, device_id="device", user_id="user", tenant_id=tenant_id,
                credential_digest=digest_token(binding_id), bound_by_user_id="user", bound_at=now,
            ))
        db.commit()
    auth.client.cookies.set("zhiju_session", CURRENT_TOKEN)


def test_password_login_sets_httponly_cookie_and_persists_only_its_digest(auth):
    before = datetime.now(timezone.utc)
    response = login(auth)
    assert response.status_code == 200
    token = response.cookies.get("zhiju_session")
    assert token and len(token) >= 43
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie
    assert token not in response.text and PASSWORD not in response.text
    assert "token" not in response.json() and "token_digest" not in response.json()
    assert response.json()["user_id"] == "user"
    assert response.json()["tenant_id"] == "tenant"
    assert response.json()["device"] is None
    with Session(auth.engine) as db:
        stored = db.scalar(select(AuthSession))
        assert stored.token_digest == hashlib.sha256(token.encode()).hexdigest()
        assert stored.device_id is None
        assert stored.status == "active"
        assert before < utc(stored.expires_at) <= before + timedelta(hours=8, seconds=5)
        assert utc(db.get(AppUser, "user").last_login_at) >= before
        audit = db.scalar(select(AuthEvent))
        assert (audit.event_type, audit.result, audit.actor_user_id) == ("login", "success", "user")
        assert audit.session_id == stored.id and audit.request_id
        assert token not in str(audit.__dict__) and PASSWORD not in str(audit.__dict__)
    assert auth.client.get(ME).status_code == 200


@pytest.mark.parametrize("environment,scheme,secure", [
    ("production", "https", True),
    ("production", "http", False),
    ("development", "https", False),
])
def test_cookie_secure_tracks_production_https(auth, environment, scheme, secure):
    auth.settings.env = environment
    origin = f"{scheme}://testserver"
    with TestClient(auth.app, base_url=origin, headers={"Origin": origin}) as client:
        response = client.post(LOGIN, json={"login_name": "owner", "password": PASSWORD})
        assert response.status_code == 200
        assert ("secure" in response.headers["set-cookie"].lower()) is secure
        response = client.post(LOGOUT)
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "max-age=0" in cookie and "httponly" in cookie and "samesite=lax" in cookie
        assert ("secure" in cookie) is secure


def test_unknown_account_and_wrong_password_return_identical_login_failure(auth):
    unknown = login(auth, login_name="missing")
    wrong = login(auth, password="wrong password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert "set-cookie" not in unknown.headers and "set-cookie" not in wrong.headers
    with Session(auth.engine) as db:
        assert db.get(AppUser, "user").failed_login_count == 1
        assert list(db.scalars(select(AuthSession))) == []
        audits = list(db.scalars(select(AuthEvent).order_by(AuthEvent.occurred_at)))
        assert [(item.event_type, item.result) for item in audits] == [("login", "failure")] * 2
        assert {item.actor_user_id for item in audits} == {None, "user"}
        assert "wrong password" not in str([item.__dict__ for item in audits])


def test_five_failures_lock_account_for_fifteen_minutes_without_extending_lock(auth):
    before = datetime.now(timezone.utc)
    for _ in range(5):
        assert login(auth, password="wrong").status_code == 401
    with Session(auth.engine) as db:
        user = db.get(AppUser, "user")
        assert user.failed_login_count == 5
        locked_until = utc(user.locked_until)
        assert before + timedelta(minutes=15) <= locked_until <= datetime.now(timezone.utc) + timedelta(minutes=15)
    assert login(auth).status_code == 401
    with Session(auth.engine) as db:
        user = db.get(AppUser, "user")
        assert user.failed_login_count == 5 and utc(user.locked_until) == locked_until
        assert user.last_login_at is None and list(db.scalars(select(AuthSession))) == []


def test_expired_lock_starts_a_new_failure_window(auth):
    with Session(auth.engine) as db:
        user = db.get(AppUser, "user")
        user.failed_login_count = 5
        user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert login(auth, password="wrong").status_code == 401
    with Session(auth.engine) as db:
        user = db.get(AppUser, "user")
        assert user.failed_login_count == 1 and user.locked_until is None
    assert login(auth).status_code == 200
    with Session(auth.engine) as db:
        user = db.get(AppUser, "user")
        assert user.failed_login_count == 0 and user.locked_until is None


@pytest.mark.parametrize("unavailable", [
    "user_suspended", "user_expired", "tenant_suspended", "tenant_expired",
    "membership_suspended", "membership_missing",
])
def test_login_requires_active_user_membership_tenant_and_both_leases(auth, unavailable):
    with Session(auth.engine) as db:
        if unavailable == "membership_missing":
            db.delete(db.get(TenantMembership, "membership"))
        else:
            model, field = unavailable.split("_")
            row = db.get({"user": AppUser, "tenant": Tenant, "membership": TenantMembership}[model], model)
            if field == "suspended":
                row.status = "suspended"
            else:
                row.lease_expires_at = datetime.now(timezone.utc)
        db.commit()
    response = login(auth)
    assert response.status_code == 401 and "set-cookie" not in response.headers
    with Session(auth.engine) as db:
        assert list(db.scalars(select(AuthSession))) == []
        assert db.scalar(select(AuthEvent)).result == "failure"


def test_super_admin_password_login_starts_without_impersonated_tenant_or_device(auth):
    with Session(auth.engine) as db:
        db.get(AppUser, "user").platform_role = "super_admin"
        db.delete(db.get(TenantMembership, "membership"))
        db.commit()
    response = auth.client.post(LOGIN, json={
        "login_name": "owner", "password": PASSWORD, "device_id": "device", "tenant_id": "tenant",
    }, headers={"X-Device-Id": "device", "X-Device-Trust-Level": "super_code_machine"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "user" and body["platform_role"] == "super_admin"
    assert body["tenant_id"] is None and body["current_tenant"] is None
    assert body["membership_role"] is None and body["memberships"] == [] and body["device"] is None
    assert "platform.tenant.manage" in body["permissions"]


def test_me_requires_a_session(auth):
    assert auth.client.get(ME).status_code == 401


def test_me_reports_real_actor_current_tenant_available_memberships_and_device(auth):
    seed_sessions(auth)
    with Session(auth.engine) as db:
        db.add(TenantMembership(user_id="user", tenant_id="other-tenant", role_code="viewer", status="suspended"))
        db.commit()
    response = auth.client.get(ME)
    assert response.status_code == 200
    body = response.json()
    assert (body["user_id"], body["display_name"], body["login_name"]) == ("user", "Owner", "owner")
    assert body["platform_role"] is None and body["membership_role"] == "owner"
    assert body["current_tenant"] == {"id": "tenant", "company_name": "First Company", "short_name": "first"}
    assert body["memberships"] == [{
        "tenant_id": "tenant", "company_name": "First Company", "short_name": "first", "role_code": "owner",
    }]
    assert body["device"] == {"id": "device", "name": "Fixture Device", "display_name": "Workstation", "trust_level": "normal"}
    assert body["permissions"] == ["channel.manage", "channel.read"]
    assert CURRENT_TOKEN not in response.text


@pytest.mark.parametrize("age_minutes", [0, 10])
def test_super_admin_can_switch_only_current_session_and_audits_real_actor(auth, age_minutes):
    seed_sessions(auth, super_admin=True, age_minutes=age_minutes)
    response = auth.client.post(SWITCH, json={"tenant_id": "other-tenant"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "user" and body["platform_role"] == "super_admin"
    assert body["tenant_id"] == "other-tenant" and body["membership_role"] is None
    assert body["current_tenant"]["company_name"] == "Other Company"
    assert body["device"]["trust_level"] == "normal"
    assert auth.client.get(ME).json()["tenant_id"] == "other-tenant"
    with Session(auth.engine) as db:
        assert db.get(AuthSession, "current").tenant_id == "other-tenant"
        assert db.get(AuthSession, "other").tenant_id == "tenant"
        audit = db.scalar(select(AuthEvent))
        assert (audit.event_type, audit.result, audit.actor_user_id, audit.actor_device_id) == ("tenant_switch", "success", "user", "device")
        assert (audit.tenant_id, audit.target_type, audit.target_id) == ("other-tenant", "tenant", "other-tenant")
        assert audit.session_id == "current" and audit.request_id


def test_ordinary_user_cannot_switch_tenant_even_on_super_code_machine(auth):
    seed_sessions(auth)
    with Session(auth.engine) as db:
        db.get(Device, "device").trust_level = "super_code_machine"
        db.commit()
    assert auth.client.post(SWITCH, json={"tenant_id": "other-tenant"}).status_code == 403
    with Session(auth.engine) as db:
        assert db.get(AuthSession, "current").tenant_id == "tenant"
        assert list(db.scalars(select(AuthEvent))) == []


@pytest.mark.parametrize("unavailable,status", [("missing", 404), ("suspended", 403), ("expired", 403)])
def test_switch_rejects_unavailable_target_before_changing_session(auth, unavailable, status):
    seed_sessions(auth, super_admin=True)
    assert auth.client.get(ME).status_code == 200
    with Session(auth.engine) as db:
        if unavailable == "suspended":
            db.get(Tenant, "other-tenant").status = "suspended"
        elif unavailable == "expired":
            db.get(Tenant, "other-tenant").lease_expires_at = datetime.now(timezone.utc)
        db.commit()
    tenant_id = "missing" if unavailable == "missing" else "other-tenant"
    assert auth.client.post(SWITCH, json={"tenant_id": tenant_id}).status_code == status
    with Session(auth.engine) as db:
        assert db.get(AuthSession, "current").tenant_id == "tenant"
        assert list(db.scalars(select(AuthEvent))) == []


@pytest.mark.parametrize("age_minutes", [0, 10])
def test_logout_revokes_only_current_session_and_disables_only_its_active_binding(auth, age_minutes):
    seed_sessions(auth, age_minutes=age_minutes)
    response = auth.client.post(LOGOUT)
    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()
    with Session(auth.engine) as db:
        current = db.get(AuthSession, "current")
        assert current.status == "revoked" and current.revoked_at and current.revoke_reason == "logout"
        assert db.get(AuthSession, "other").status == "active"
        assert db.get(DeviceUserBinding, "binding").auto_login_enabled is False
        assert db.get(DeviceUserBinding, "binding").status == "active"
        assert db.get(DeviceUserBinding, "other-binding").auto_login_enabled is True
        audit = db.scalar(select(AuthEvent))
        assert (audit.event_type, audit.actor_user_id, audit.actor_device_id) == ("logout", "user", "device")
        assert audit.session_id == "current" and CURRENT_TOKEN not in str(audit.__dict__)
    auth.client.cookies.set("zhiju_session", CURRENT_TOKEN)
    assert auth.client.get(ME).status_code == 401


def test_logout_can_clear_an_inactive_users_session(auth):
    seed_sessions(auth)
    with Session(auth.engine) as db:
        db.get(AppUser, "user").status = "suspended"
        db.commit()
    assert auth.client.post(LOGOUT).status_code == 200
    with Session(auth.engine) as db:
        assert db.get(AuthSession, "current").status == "revoked"


@pytest.mark.parametrize("token", [None, "unknown"])
def test_logout_without_a_known_session_still_clears_cookie(auth, token):
    if token:
        auth.client.cookies.set("zhiju_session", token)
    response = auth.client.post(LOGOUT)
    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()
    with Session(auth.engine) as db:
        assert list(db.scalars(select(AuthEvent))) == []


@pytest.mark.parametrize("route,payload", [(LOGIN, {"login_name": "owner", "password": PASSWORD}), (LOGOUT, {}), (SWITCH, {"tenant_id": "other-tenant"})])
@pytest.mark.parametrize("origin", [None, "null", "https://other.example"])
def test_auth_writes_require_matching_origin_before_mutation(auth, route, payload, origin):
    seed_sessions(auth, super_admin=True)
    auth.client.headers.pop("origin", None)
    headers = {} if origin is None else {"Origin": origin}
    assert auth.client.post(route, json=payload, headers=headers).status_code == 403
    with Session(auth.engine) as db:
        assert db.get(AuthSession, "current").status == "active"
        assert db.get(AuthSession, "current").tenant_id == "tenant"
        assert db.get(DeviceUserBinding, "binding").auto_login_enabled is True
        assert len(list(db.scalars(select(AuthSession)))) == 2
        assert list(db.scalars(select(AuthEvent))) == []


@pytest.mark.parametrize("route,payload", [(LOGIN, {"login_name": "owner", "password": PASSWORD}), (LOGOUT, {}), (SWITCH, {"tenant_id": "other-tenant"})])
def test_auth_mutation_rolls_back_when_audit_insert_fails(auth, route, payload):
    if route != LOGIN:
        seed_sessions(auth, super_admin=True, age_minutes=10)

    def reject_audit(mapper, connection, target):
        raise RuntimeError("simulated database failure")

    event.listen(AuthEvent, "before_insert", reject_audit)
    try:
        with TestClient(auth.app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}) as client:
            if route != LOGIN:
                client.cookies.set("zhiju_session", CURRENT_TOKEN)
            response = client.post(route, json=payload)
        assert response.status_code == 500 and "set-cookie" not in response.headers
    finally:
        event.remove(AuthEvent, "before_insert", reject_audit)
    with Session(auth.engine) as db:
        assert list(db.scalars(select(AuthEvent))) == []
        if route == LOGIN:
            assert list(db.scalars(select(AuthSession))) == []
            assert db.get(AppUser, "user").last_login_at is None
        else:
            assert db.get(AuthSession, "current").status == "active"
            assert db.get(AuthSession, "current").tenant_id == "tenant"
            assert db.get(DeviceUserBinding, "binding").auto_login_enabled is True


def test_auth_changes_are_not_broadcast_on_the_legacy_business_event_stream(auth, monkeypatch):
    from zhiju.realtime import broker

    monkeypatch.setattr("zhiju.realtime.get_settings", lambda: SimpleNamespace(
        realtime_hub_url="", device_role="studio", device_key="fixture",
    ))
    queue = broker.subscribe()
    try:
        assert login(auth).status_code == 200
        assert queue.empty()
    finally:
        broker.unsubscribe(queue)
