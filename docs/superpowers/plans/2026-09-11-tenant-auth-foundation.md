# Tenant Auth Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the tenant, password-login, RBAC, server-session, trusted-device, tenant-switching, and logout foundation without yet exposing unscoped tenant business data.

**Architecture:** Authentication is an additive subsystem with its own platform database dependency. A signed-in principal contains the real user, current tenant membership, device, and permissions; tenant business enforcement remains disabled until the separate all-table isolation plan is complete. Super-admin platform mutations require both the `super_admin` platform role and a `super_code_machine` device.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, MySQL, Alembic, Pydantic, argon2-cffi, vanilla JavaScript, pytest

**Spec:** `docs/superpowers/specs/2026-09-11-tenant-auth-device-system-design.md`

## Global Constraints

- The only visible login method is login name plus password.
- Never store or log a plaintext password, session token, device secret, OAuth token, or Cookie.
- A normal user on the super code machine never gains platform permissions.
- A super admin on a non-super device cannot perform high-risk platform mutations.
- Super-admin tenant switching preserves the real super-admin actor identity.
- Existing production data and devices are not changed by this phase.
- Authentication enforcement must remain off until the all-table tenant-isolation migration and trusted-device enrollment are accepted.
- All implementation stays on `feature/tenant-auth-system`; no merge, deployment, production migration, or production write is authorized by this plan.

---

### Task 1: Authentication models and additive migration

**Files:**
- Create: `backend/zhiju/models/auth.py`
- Modify: `backend/zhiju/models/identity.py`
- Modify: `backend/zhiju/models/__init__.py`
- Create: `backend/alembic/versions/a9c4e7b2d613_add_tenant_auth_foundation.py`
- Test: `backend/tests/test_auth_model_contract.py`

**Interfaces:**
- Produces: `Tenant`, `AppUser`, `TenantMembership`, `Permission`, `RolePermission`, `AuthSession`, `DeviceUserBinding`, `AuthEvent`.
- Produces: `Device.trust_level` with `super_code_machine`, `code_machine`, `production_device`, and `normal` values.
- Consumes: existing `Base`, `IdMixin`, `TimestampMixin`, and `Device`.

- [ ] **Step 1: Write failing model metadata tests**

```python
def test_auth_foundation_tables_and_device_trust_are_registered():
    expected = {
        "tenants", "app_users", "tenant_memberships", "permissions",
        "role_permissions", "auth_sessions", "device_user_bindings", "auth_events",
    }
    assert expected <= set(Base.metadata.tables)
    assert "trust_level" in Base.metadata.tables["devices"].c

def test_password_and_secret_columns_are_digest_only():
    assert "password_hash" in Base.metadata.tables["app_users"].c
    assert "token_digest" in Base.metadata.tables["auth_sessions"].c
    assert "credential_digest" in Base.metadata.tables["device_user_bindings"].c
    assert "password" not in Base.metadata.tables["app_users"].c
```

- [ ] **Step 2: Run the model test and verify RED**

Run: `.venv/bin/pytest -q backend/tests/test_auth_model_contract.py`

Expected: failure because the auth tables and `Device.trust_level` do not exist.

- [ ] **Step 3: Implement the exact model contracts**

Create the eight models with these stable role/status values:

```python
PLATFORM_ROLES = {"super_admin"}
MEMBERSHIP_ROLES = {"owner", "admin", "operator", "viewer"}
ACCOUNT_STATUSES = {"active", "suspended"}
SESSION_STATUSES = {"active", "revoked", "expired"}
BINDING_STATUSES = {"active", "suspended", "revoked"}
```

Enforce one membership per `(tenant_id, user_id)`, one role-permission pair, unique `AppUser.login_name`, unique `Tenant.short_name`, and unique `(device_id, user_id, tenant_id)` binding. Add indexes for active session token digest, user login name, tenant membership lookup, and active device binding lookup.

- [ ] **Step 4: Generate and hand-review an additive Alembic migration**

The migration creates only the eight new tables and adds nullable-safe `devices.trust_level` with server default `normal`. It must not alter existing business tables or seed production identities.

- [ ] **Step 5: Run focused verification**

Run: `.venv/bin/pytest -q backend/tests/test_auth_model_contract.py`

Expected: PASS.

Run: `PYTHONPATH=backend .venv/bin/alembic -c alembic.ini heads`

Expected: exactly one head containing the new revision.

- [ ] **Step 6: Commit**

```bash
git add backend/zhiju/models backend/alembic/versions backend/tests/test_auth_model_contract.py
git commit -m "feat: add tenant authentication models"
```

### Task 2: Password hashing and opaque session tokens

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements-runtime.txt`
- Modify: `uv.lock`
- Create: `backend/zhiju/security.py`
- Test: `backend/tests/test_security.py`

**Interfaces:**
- Produces: `hash_password(password: str) -> str`.
- Produces: `verify_password(password: str, password_hash: str) -> bool`.
- Produces: `new_opaque_token() -> str` and `digest_token(token: str) -> str`.
- Consumes: `argon2-cffi>=23,<26`.

- [ ] **Step 1: Write failing security tests**

```python
def test_password_hash_is_argon2_and_verifies():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)

def test_opaque_tokens_are_only_looked_up_by_digest():
    token = new_opaque_token()
    assert len(token) >= 43
    assert token not in digest_token(token)
    assert digest_token(token) == digest_token(token)
```

- [ ] **Step 2: Run the security test and verify RED**

Run: `.venv/bin/pytest -q backend/tests/test_security.py`

Expected: import failure because `zhiju.security` does not exist.

- [ ] **Step 3: Implement the helpers**

Use `argon2.PasswordHasher` with Argon2id defaults. Catch only `VerifyMismatchError`, `VerificationError`, and `InvalidHashError` during verification and return false. Generate tokens with `secrets.token_urlsafe(48)` and store a SHA-256 digest because the digest replaces a database lookup of the secret token.

- [ ] **Step 4: Update dependency lock and run focused tests**

Run: `uv lock`

Run: `.venv/bin/pytest -q backend/tests/test_security.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements-runtime.txt uv.lock backend/zhiju/security.py backend/tests/test_security.py
git commit -m "feat: add password and session security primitives"
```

### Task 3: Principal resolution, RBAC, and device gate

**Files:**
- Create: `backend/zhiju/auth_context.py`
- Modify: `backend/zhiju/permissions.py`
- Test: `backend/tests/test_auth_context.py`

**Interfaces:**
- Produces: immutable `Principal(user_id, tenant_id, membership_role, platform_role, device_id, device_trust_level, permissions)`.
- Produces: `get_optional_principal(request: Request, session: Session = Depends(get_db)) -> Principal | None`.
- Produces: `get_current_principal(...) -> Principal` returning 401 when absent or inactive.
- Produces: `require_permission(code: str)` FastAPI dependency factory.
- Produces: `require_super_code_machine(principal: Principal = Depends(get_current_principal)) -> Principal`.
- Consumes: `digest_token`, auth models, and the `zhiju_session` HttpOnly cookie.

- [ ] **Step 1: Write failing principal tests**

Cover: active session success, revoked/expired session 401, suspended user 401, suspended/expired tenant 403, missing membership 403, owner permission success, viewer write denial, normal user on super machine denial, super admin on normal machine denial, and super admin on super machine success.

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest -q backend/tests/test_auth_context.py`

Expected: import failure for `zhiju.auth_context`.

- [ ] **Step 3: Implement principal resolution**

Resolve one active `AuthSession` by token digest, then load `AppUser`, `Device`, current `Tenant`, `TenantMembership`, and stable permission codes. Update `last_seen_at` at most once per five minutes. Never accept `user_id`, `device_id`, `platform_role`, or permissions from request headers.

- [ ] **Step 4: Implement permission dependencies**

`require_permission` returns 403 when the principal lacks the exact permission. `require_super_code_machine` requires both `platform_role == "super_admin"` and `device_trust_level == "super_code_machine"`.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest -q backend/tests/test_auth_context.py`

Expected: PASS.

```bash
git add backend/zhiju/auth_context.py backend/zhiju/permissions.py backend/tests/test_auth_context.py
git commit -m "feat: resolve authenticated principals and permissions"
```

### Task 4: Login, logout, current user, and tenant switching service

**Files:**
- Create: `backend/zhiju/services/auth.py`
- Create: `backend/zhiju/schemas/auth.py`
- Create: `backend/zhiju/api/auth.py`
- Modify: `backend/zhiju/app.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Produces: `POST /api/v3/auth/login` accepting `{login_name, password}`.
- Produces: `POST /api/v3/auth/logout`.
- Produces: `GET /api/v3/auth/me`.
- Produces: `POST /api/v3/auth/switch-tenant` accepting `{tenant_id}` for super admin.
- Produces: cookie name `zhiju_session`, path `/`, HttpOnly, SameSite `lax`, `Secure` when environment is production HTTPS.
- Consumes: Task 2 security helpers and Task 3 principal dependencies.

- [ ] **Step 1: Write failing API tests**

Tests must assert successful login sets a cookie without returning the token in JSON; wrong account and wrong password return the same 401 text; logout revokes the database session and clears the Cookie; `/auth/me` reports the real actor and current tenant; tenant switching is allowed only for super admin and writes an auth event.

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest -q backend/tests/test_auth_api.py`

Expected: 404 for the new auth routes.

- [ ] **Step 3: Implement login and logout transactions**

On login, lock the user row, enforce status/lease/lockout, verify the Argon2id hash, reset failures, create `AuthSession`, update last login, and record `AuthEvent`. On failure, increment the failure counter and apply a 15-minute lock after five consecutive failures. On logout, revoke only the current session, set an active device binding to `auto_login_enabled=False`, record `AuthEvent`, and expire the cookie.

- [ ] **Step 4: Implement current-user and tenant-switching responses**

`/auth/me` returns user display name, login name, platform role, current tenant, available memberships, device display/trust, and permissions. Tenant switching changes only the current session tenant and records the real super-admin actor.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest -q backend/tests/test_auth_api.py`

Expected: PASS.

```bash
git add backend/zhiju/api/auth.py backend/zhiju/schemas/auth.py backend/zhiju/services/auth.py backend/zhiju/app.py backend/tests/test_auth_api.py
git commit -m "feat: add password login logout and tenant switching"
```

### Task 5: Platform tenant, user, and device-binding administration

**Files:**
- Create: `backend/zhiju/services/platform_admin.py`
- Create: `backend/zhiju/schemas/platform_admin.py`
- Create: `backend/zhiju/api/platform_admin.py`
- Modify: `backend/zhiju/app.py`
- Test: `backend/tests/test_platform_admin_api.py`

**Interfaces:**
- Produces: `/api/v3/platform/tenants` list/create/update endpoints.
- Produces: `/api/v3/platform/tenants/{tenant_id}/users` list/create/update endpoints.
- Produces: `/api/v3/platform/device-bindings` create/revoke endpoints.
- Consumes: `require_super_code_machine` for tenant creation, owner replacement, super-admin changes, and device binding.

- [ ] **Step 1: Write failing platform tests**

Cover tenant creation with exactly one owner, duplicate login rejection, owner uniqueness, status and lease validation, role assignment, password reset revoking all user sessions, device binding only under the dual super gate, and no raw device secret in the JSON response or audit event.

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest -q backend/tests/test_platform_admin_api.py`

Expected: 404 for platform routes.

- [ ] **Step 3: Implement transactional tenant and user administration**

Create tenant and owner in one transaction. A tenant owner can manage admin/operator/viewer users in its tenant through separate tenant-scoped endpoints; only dual-gated super admin creates tenants, changes owners, or binds trusted devices.

- [ ] **Step 4: Implement device enrollment output boundary**

The create-binding service returns the raw one-time device secret exactly once to a local enrollment writer, not to ordinary list/detail APIs. Persist only `credential_digest`. Revocation marks the binding revoked and revokes sessions for the same binding.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest -q backend/tests/test_platform_admin_api.py`

Expected: PASS.

```bash
git add backend/zhiju/api/platform_admin.py backend/zhiju/schemas/platform_admin.py backend/zhiju/services/platform_admin.py backend/zhiju/app.py backend/tests/test_platform_admin_api.py
git commit -m "feat: manage tenants users and trusted devices"
```

### Task 6: Login, account menu, tenant switcher, and logout UI

**Files:**
- Create: `assets/auth-state.js`
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Modify: `index.html`
- Test: `backend/tests/test_auth_frontend_contract.py`

**Interfaces:**
- Produces: `ZhijuAuthState.resolveBootstrap(request)`, `can(permission)`, and `logout(request)`.
- Consumes: `/auth/login`, `/auth/logout`, `/auth/me`, and `/auth/switch-tenant`.

- [ ] **Step 1: Write failing Node and HTML contract tests**

Test unauthenticated bootstrap renders only login; successful login loads the application; account menu shows display name, company, and logout; super admin sees a tenant switcher and persistent current-company banner; logout returns to login and cannot immediately auto-login.

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest -q backend/tests/test_auth_frontend_contract.py`

Expected: failure because `auth-state.js` and login UI do not exist.

- [ ] **Step 3: Implement the isolated auth helper and login shell**

Do not add auth branches throughout every page. Bootstrap once before `loadView`, store the `/auth/me` response in one auth state, derive visible controls from stable permission codes, and send all requests through the existing API helper with cookies.

- [ ] **Step 4: Implement account menu and logout**

Add a top-right account button, current-company banner for super admin, switch-tenant action, and logout action. On 401, clear in-memory page state and render the login shell without exposing the previous tenant DOM.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest -q backend/tests/test_auth_frontend_contract.py`

Expected: PASS.

```bash
git add assets/auth-state.js assets/app.js assets/styles.css index.html backend/tests/test_auth_frontend_contract.py
git commit -m "feat: add account login switching and logout UI"
```

### Task 7: Foundation integration verification

**Files:**
- Modify only if a verification failure identifies a defect in Tasks 1-6.

**Interfaces:**
- Consumes all prior task interfaces.
- Produces a green additive auth foundation ready for the separate tenant-data-isolation plan.

- [ ] **Step 1: Run the focused auth suite**

Run: `.venv/bin/pytest -q backend/tests/test_auth_model_contract.py backend/tests/test_security.py backend/tests/test_auth_context.py backend/tests/test_auth_api.py backend/tests/test_platform_admin_api.py backend/tests/test_auth_frontend_contract.py`

Expected: PASS.

- [ ] **Step 2: Run the complete regression suite**

Run: `.venv/bin/pytest -q`

Expected: zero failures.

- [ ] **Step 3: Run structural checks**

Run: `.venv/bin/python -m compileall -q backend run_v3.py launcher.py`

Run: `node --check assets/app.js && node --check assets/auth-state.js`

Run: `git diff --check`

Expected: all commands exit 0.

- [ ] **Step 4: Verify the phase boundary**

Confirm auth enforcement is not enabled for existing business routes and no production data, configuration, Keychain item, service, device, or database was changed. Record that full business-route enforcement is blocked on the tenant-data-isolation plan, not on test status.

- [ ] **Step 5: Commit verification-only fixes if required**

If a verification command required a code correction, commit only that correction with its regression test. If no correction was required, do not create an empty commit.
