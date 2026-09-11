from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, UniqueConstraint

from zhiju.models import Base


ROOT = Path(__file__).resolve().parents[2]


AUTH_TABLE_COLUMNS = {
    "tenants": {
        "id",
        "company_name",
        "short_name",
        "status",
        "lease_expires_at",
        "plan_code",
        "contact_name",
        "contact_phone",
        "remark",
        "created_by_user_id",
        "created_at",
        "updated_at",
        "suspended_at",
        "suspended_reason",
    },
    "app_users": {
        "id",
        "display_name",
        "login_name",
        "password_hash",
        "platform_role",
        "status",
        "lease_expires_at",
        "password_changed_at",
        "last_login_at",
        "failed_login_count",
        "locked_until",
        "created_by_user_id",
        "created_at",
        "updated_at",
        "suspended_at",
        "suspended_reason",
    },
    "tenant_memberships": {
        "id",
        "tenant_id",
        "user_id",
        "role_code",
        "status",
        "created_by_user_id",
        "created_at",
        "updated_at",
    },
    "permissions": {"id", "code", "name_zh", "created_at", "updated_at"},
    "role_permissions": {
        "id",
        "role_code",
        "permission_id",
        "created_at",
        "updated_at",
    },
    "auth_sessions": {
        "id",
        "user_id",
        "tenant_id",
        "device_id",
        "token_digest",
        "status",
        "expires_at",
        "last_seen_at",
        "revoked_at",
        "revoke_reason",
        "created_at",
    },
    "device_user_bindings": {
        "id",
        "device_id",
        "user_id",
        "tenant_id",
        "is_default",
        "auto_login_enabled",
        "credential_digest",
        "expires_at",
        "last_used_at",
        "bound_by_user_id",
        "bound_at",
        "status",
        "revoked_at",
        "revoke_reason",
    },
    "auth_events": {
        "id",
        "tenant_id",
        "actor_user_id",
        "actor_device_id",
        "session_id",
        "request_id",
        "event_type",
        "result",
        "target_type",
        "target_id",
        "login_name",
        "detail",
        "reason",
        "occurred_at",
    },
}


def _check_sql(table_name: str) -> str:
    return " ".join(
        str(constraint.sqltext)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    )


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_auth_foundation_tables_and_device_trust_are_registered() -> None:
    assert AUTH_TABLE_COLUMNS.keys() <= Base.metadata.tables.keys()
    assert "trust_level" in Base.metadata.tables["devices"].c


def test_auth_foundation_tables_match_the_designed_fields() -> None:
    for table_name, expected_columns in AUTH_TABLE_COLUMNS.items():
        assert expected_columns == set(Base.metadata.tables[table_name].c.keys())


def test_password_and_secret_columns_are_digest_only() -> None:
    assert "password_hash" in Base.metadata.tables["app_users"].c
    assert "token_digest" in Base.metadata.tables["auth_sessions"].c
    assert "credential_digest" in Base.metadata.tables["device_user_bindings"].c
    assert "password" not in Base.metadata.tables["app_users"].c


def test_auth_role_status_and_device_trust_values_are_constrained() -> None:
    assert "platform_role IS NULL OR platform_role IN ('super_admin')" in _check_sql(
        "app_users"
    )
    assert "role_code IN ('owner','admin','operator','viewer')" in _check_sql(
        "tenant_memberships"
    )
    assert (
        "role_code IN ('super_admin','owner','admin','operator','viewer')"
        in _check_sql("role_permissions")
    )
    assert "status IN ('active','suspended')" in _check_sql("tenants")
    assert "status IN ('active','suspended')" in _check_sql("app_users")
    assert "status IN ('active','suspended')" in _check_sql("tenant_memberships")
    assert "status IN ('active','revoked','expired')" in _check_sql("auth_sessions")
    assert (
        "status IN ('active','suspended','revoked')"
        in _check_sql("device_user_bindings")
    )
    assert (
        "trust_level IN "
        "('super_code_machine','code_machine','production_device','normal')"
        in _check_sql("devices")
    )


def test_auth_identity_pairs_are_unique() -> None:
    assert ("short_name",) in _unique_column_sets("tenants")
    assert ("login_name",) in _unique_column_sets("app_users")
    assert ("tenant_id", "user_id") in _unique_column_sets("tenant_memberships")
    assert ("role_code", "permission_id") in _unique_column_sets(
        "role_permissions"
    )
    assert ("device_id", "user_id", "tenant_id") in _unique_column_sets(
        "device_user_bindings"
    )


def test_auth_lookup_indexes_cover_the_expected_queries() -> None:
    index_columns = {
        tuple(column.name for column in index.columns)
        for table_name in AUTH_TABLE_COLUMNS
        for index in Base.metadata.tables[table_name].indexes
    }

    assert ("token_digest", "status") in index_columns
    assert ("login_name", "status") in index_columns
    assert ("user_id", "status") in index_columns
    assert ("credential_digest", "status") in index_columns
    assert ("device_id", "status", "auto_login_enabled") in index_columns


def test_tenant_auth_migration_is_additive_and_follows_current_head() -> None:
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    revisions = {
        revision.revision: revision
        for revision in ScriptDirectory.from_config(config).walk_revisions()
    }

    assert "a9c4e7b2d613" in revisions
    revision = revisions["a9c4e7b2d613"]
    assert revision.down_revision == "6f3a2c9d1e40"

    class RecordingOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

        def f(self, name: str) -> str:
            return name

        def __getattr__(self, name: str):
            def record(*args: object, **kwargs: object) -> None:
                self.calls.append((name, args, kwargs))

            return record

    operations = RecordingOperations()
    revision.module.op = operations
    revision.module.upgrade()

    created_tables = {
        args[0] for name, args, _ in operations.calls if name == "create_table"
    }
    added_columns = [
        args for name, args, _ in operations.calls if name == "add_column"
    ]
    operation_names = {name for name, _, _ in operations.calls}

    assert created_tables == set(AUTH_TABLE_COLUMNS)
    assert len(added_columns) == 1
    assert added_columns[0][0] == "devices"
    trust_column = added_columns[0][1]
    assert trust_column.name == "trust_level"
    assert trust_column.nullable is False
    assert str(trust_column.server_default.arg) == "normal"
    assert operation_names <= {
        "add_column",
        "create_check_constraint",
        "create_index",
        "create_table",
    }
