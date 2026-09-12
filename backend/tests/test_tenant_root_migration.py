from datetime import datetime
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from zhiju.models import Base


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TENANT = "00000000-0000-4000-8000-000000000001"
ROOT_TABLES = (
    "channels", "dramas", "production_batches", "google_accounts",
    "integration_accounts", "channel_drama_types", "image_workspace_settings",
    "demo_data_batches", "feishu_sync_runs", "media_assets", "audit_events",
    "system_events", "api_request_logs", "quota_usage_logs",
)
AUTH_REFERENCE_TABLES = (
    "tenant_memberships", "device_user_bindings", "auth_sessions", "auth_events",
)
PERMISSIONS = {
    "tenant.read": "查看主账号", "tenant.manage": "管理主账号",
    "user.read": "查看用户", "user.manage": "管理用户",
    "channel.read": "查看频道", "channel.manage": "管理频道", "channel.delete": "永久删除频道",
    "schedule.manage": "管理排期", "workorder.manage": "管理工单", "package.manage": "管理运营包",
    "media.manage": "管理素材", "youtube.sync": "同步 YouTube", "audit.read": "查看审计记录",
    "platform.tenant.manage": "管理平台主账号", "platform.device.manage": "管理平台设备",
    "platform.environment.manage": "管理运行环境",
}
ROLE_CODES = {
    "super_admin": set(PERMISSIONS),
    "owner": {code for code in PERMISSIONS if not code.startswith("platform.")},
    "admin": {"tenant.read", "user.read", "user.manage", "channel.read", "channel.manage",
              "schedule.manage", "workorder.manage", "package.manage", "media.manage", "youtube.sync", "audit.read"},
    "operator": {"tenant.read", "channel.read", "schedule.manage", "workorder.manage",
                 "package.manage", "media.manage", "youtube.sync"},
    "viewer": {"tenant.read", "user.read", "channel.read", "audit.read"},
}


@pytest.fixture
def migration():
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    revisions = {
        revision.revision: revision
        for revision in ScriptDirectory.from_config(config).walk_revisions()
    }
    revision = revisions.get("b1d4e7f2a610")
    return revision.module if revision else None


@pytest.fixture
def database():
    # In-memory legacy root rows plus the actual seed-table contracts.
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        Base.metadata.create_all(connection, tables=[
            Base.metadata.tables[name] for name in ("app_users", "tenants", "permissions", "role_permissions")
        ])
        metadata = sa.MetaData()
        for name in ROOT_TABLES:
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True),
                     sa.Column("legacy_payload", sa.String(100)))
        for name in AUTH_REFERENCE_TABLES:
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True),
                     sa.Column("tenant_id", sa.String(36)))
        metadata.create_all(connection)
        for name in ROOT_TABLES:
            connection.execute(metadata.tables[name].insert(), {"id": "old-row", "legacy_payload": name})
        yield connection
    engine.dispose()


def install_operations(monkeypatch, migration, connection):
    assert migration is not None, "Task 3 migration is missing"
    assert migration.down_revision == "a9c4e7b2d613"
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))


def test_upgrade_seeds_existing_tenant_and_backfills_every_root(migration, database, monkeypatch):
    install_operations(monkeypatch, migration, database)
    migration.upgrade()

    tenant = database.execute(sa.select(Base.metadata.tables["tenants"])).mappings().one()
    assert migration.DEFAULT_EXISTING_TENANT_ID == DEFAULT_TENANT
    assert (tenant["id"], tenant["company_name"], tenant["short_name"], tenant["status"]) == (
        DEFAULT_TENANT, "智矩现有业务", "智矩现有业务", "active",
    )
    assert tenant["lease_expires_at"] == datetime(2099, 12, 31, 23, 59, 59)
    assert tenant["created_by_user_id"] is None
    for name in ROOT_TABLES:
        row = database.execute(sa.text(f"SELECT id, legacy_payload, tenant_id FROM {name}")).one()
        assert tuple(row) == ("old-row", name, DEFAULT_TENANT)
        column = next(c for c in sa.inspect(database).get_columns(name) if c["name"] == "tenant_id")
        assert column["nullable"] is True
        assert any(index["name"] == f"ix_{name}_tenant_id" and index["column_names"] == ["tenant_id"]
                   for index in sa.inspect(database).get_indexes(name))
        database.execute(sa.text(f"INSERT INTO {name} (id) VALUES ('new-null-row')"))
    assert database.scalar(sa.text("SELECT COUNT(*) FROM app_users")) == 0
    for name in AUTH_REFERENCE_TABLES:
        assert database.scalar(sa.text(f"SELECT COUNT(*) FROM {name}")) == 0


def test_permission_seed_has_exact_role_grants_and_is_idempotent(migration, database, monkeypatch):
    install_operations(monkeypatch, migration, database)
    migration.upgrade()
    rows = database.execute(sa.text("SELECT id, code, name_zh FROM permissions")).all()
    assert {(id_, code, name) for id_, code, name in rows} == {
        (code, code, name) for code, name in PERMISSIONS.items()
    }
    rows = database.execute(sa.text("SELECT role_code, permission_id FROM role_permissions")).all()
    assert set(rows) == {(role, code) for role, codes in ROLE_CODES.items() for code in codes}
    database.execute(sa.text("UPDATE tenants SET short_name = '已修改简称', lease_expires_at = '2030-01-01 00:00:00'"))
    database.execute(sa.text("UPDATE permissions SET name_zh = '自定名称' WHERE code = 'tenant.read'"))
    migration._seed_default_tenant_and_permissions()
    assert database.scalar(sa.text("SELECT COUNT(*) FROM tenants")) == 1
    assert database.scalar(sa.text("SELECT short_name FROM tenants")) == "已修改简称"
    assert database.scalar(sa.select(Base.metadata.tables["tenants"].c.lease_expires_at)) == datetime(2030, 1, 1)
    assert database.scalar(sa.text("SELECT COUNT(*) FROM permissions")) == 16
    assert database.scalar(sa.text("SELECT COUNT(*) FROM role_permissions")) == 51
    assert database.scalar(sa.text("SELECT name_zh FROM permissions WHERE code = 'tenant.read'")) == "自定名称"


def test_seed_reuses_existing_permission_ids_and_grants(migration, database, monkeypatch):
    install_operations(monkeypatch, migration, database)
    database.execute(Base.metadata.tables["permissions"].insert(),
                     {"id": "existing-permission", "code": "tenant.read", "name_zh": "自定名称"})
    database.execute(Base.metadata.tables["role_permissions"].insert(),
                     {"id": "existing-role", "role_code": "viewer", "permission_id": "existing-permission"})
    migration.upgrade()
    assert database.scalar(sa.text("SELECT COUNT(*) FROM permissions")) == 16
    assert database.scalar(sa.text("SELECT COUNT(*) FROM role_permissions")) == 51
    assert database.scalar(sa.text("SELECT name_zh FROM permissions WHERE id = 'existing-permission'")) == "自定名称"
    assert database.scalar(sa.text("SELECT id FROM role_permissions WHERE role_code = 'viewer' AND permission_id = 'existing-permission'")) == "existing-role"
    assert database.scalar(sa.text("SELECT COUNT(*) FROM role_permissions WHERE permission_id = 'existing-permission'")) == 5


@pytest.mark.parametrize("referenced_table", ROOT_TABLES + AUTH_REFERENCE_TABLES)
def test_downgrade_refuses_business_references_before_any_schema_change(
    migration, database, monkeypatch, referenced_table,
):
    install_operations(monkeypatch, migration, database)
    migration.upgrade()
    for name in ROOT_TABLES:
        database.execute(sa.text(f"DELETE FROM {name}"))
    database.execute(sa.text(f"INSERT INTO {referenced_table} (id, tenant_id) VALUES ('reference', :tenant)"),
                     {"tenant": DEFAULT_TENANT})

    with pytest.raises(RuntimeError, match=referenced_table):
        migration.downgrade()

    assert database.scalar(sa.text("SELECT COUNT(*) FROM tenants WHERE id = :tenant"), {"tenant": DEFAULT_TENANT}) == 1
    for name in ROOT_TABLES:
        assert "tenant_id" in {column["name"] for column in sa.inspect(database).get_columns(name)}


def test_downgrade_empty_roots_removes_default_tenant_and_scope_columns(migration, database, monkeypatch):
    install_operations(monkeypatch, migration, database)
    migration.upgrade()
    for name in ROOT_TABLES:
        database.execute(sa.text(f"DELETE FROM {name}"))
    migration.downgrade()
    assert database.scalar(sa.text("SELECT COUNT(*) FROM tenants")) == 0
    for name in ROOT_TABLES:
        assert "tenant_id" not in {column["name"] for column in sa.inspect(database).get_columns(name)}


def test_downgrade_preserves_other_tenants_root_ownership(migration, database, monkeypatch):
    install_operations(monkeypatch, migration, database)
    migration.upgrade()
    for name in ROOT_TABLES:
        database.execute(sa.text(f"DELETE FROM {name}"))
    database.execute(sa.text("INSERT INTO channels (id, tenant_id) VALUES ('other-channel', 'other-tenant')"))

    with pytest.raises(RuntimeError, match="channels"):
        migration.downgrade()

    assert database.scalar(sa.text("SELECT tenant_id FROM channels WHERE id = 'other-channel'")) == "other-tenant"


def test_upgrade_mysql_ddl_matches_nullable_root_indexes(migration, monkeypatch):
    assert migration is not None, "Task 3 migration is missing"
    output = StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    sql = output.getvalue()
    for name in ROOT_TABLES:
        assert f"ALTER TABLE {name} ADD COLUMN tenant_id VARCHAR(36)" in sql
        assert f"CREATE INDEX ix_{name}_tenant_id ON {name} (tenant_id)" in sql
    assert "tenant_id VARCHAR(36) NOT NULL" not in sql
    assert "CREATE TABLE" not in sql
    assert "INSERT INTO app_users" not in sql
    assert "INSERT INTO device_user_bindings" not in sql
