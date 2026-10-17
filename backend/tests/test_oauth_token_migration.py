import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from zhiju.models import Base


ROOT = Path(__file__).resolve().parents[2]


def migration():
    path = ROOT / "backend/alembic/versions/8c14a201d002_complete_oauth_token_storage.py"
    spec = importlib.util.spec_from_file_location("complete_token_storage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_token_table_is_created_with_tenant_links():
    module = migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        inspector = sa.inspect(connection)
        assert "oauth_token_secrets" in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("oauth_token_secrets")} == {
            "ix_oauth_token_secrets_tenant_id", "ix_oauth_token_secrets_t_oauth_grant_id",
        }
        assert inspector.get_foreign_keys("oauth_token_secrets")[0]["constrained_columns"] == ["tenant_id", "oauth_grant_id"]
    engine.dispose()


@pytest.mark.parametrize("missing_index", [False, True])
def test_existing_cloud_tokens_survive_upgrade_retry_and_downgrade(missing_index):
    module = migration()
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO oauth_token_secrets (id,tenant_id,oauth_grant_id,encrypted_payload) VALUES ('secret-a','tenant-a','grant-a','existing-ciphertext')"))
        if missing_index:
            connection.exec_driver_sql("DROP INDEX ix_oauth_token_secrets_t_oauth_grant_id")
        before = list(connection.execute(sa.text("SELECT * FROM oauth_token_secrets")))
        statements = []
        sa.event.listen(connection, "before_cursor_execute", lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()
        module.downgrade()
        assert list(connection.execute(sa.text("SELECT * FROM oauth_token_secrets"))) == before
        writes = [statement for statement in statements if statement.lstrip().upper().startswith(("CREATE", "DROP", "ALTER", "INSERT", "UPDATE", "DELETE"))]
        assert len(writes) == (1 if missing_index else 0)
        if writes:
            assert writes[0].startswith("CREATE INDEX ix_oauth_token_secrets_t_oauth_grant_id")
    engine.dispose()


def test_local_and_cloud_upgrades_share_one_forward_chain():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == ["8c14a201d002"]
    assert [revision.revision for revision in scripts.iterate_revisions("head", "0d7a4c9e12f6")] == ["8c14a201d002", "7b14a201d001", "6a81c4d290fe"]
    assert [revision.revision for revision in scripts.iterate_revisions("head", "7b14a201d001")] == ["8c14a201d002"]
