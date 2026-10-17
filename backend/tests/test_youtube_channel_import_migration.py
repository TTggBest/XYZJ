import importlib.util
from pathlib import Path


def load_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0d7a4c9e12f6_add_youtube_channel_import_sessions.py"
    )
    spec = importlib.util.spec_from_file_location("youtube_channel_import_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_upgrade_resumes_after_mysql_applied_only_the_first_table_changes(monkeypatch) -> None:
    migration = load_migration()
    operations: list[tuple[str, str]] = []

    class Inspector:
        def get_unique_constraints(self, table_name):
            assert table_name == "google_accounts"
            return [{"name": "uq_google_accounts_tenant_email"}]

        def get_table_names(self):
            return ["google_accounts", "youtube_channel_import_sessions"]

        def get_indexes(self, table_name):
            assert table_name == "youtube_channel_import_sessions"
            return [
                {"name": "fk_youtube_channel_import_sessions_auth_session_id_auth_sessions"},
                {"name": "fk_youtube_channel_import_sessions_user_id_app_users"},
            ]

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.sa, "inspect", lambda bind: Inspector())
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table_name, **kwargs: operations.append(("drop_constraint", name)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_unique_constraint",
        lambda name, table_name, columns: operations.append(("create_unique_constraint", name)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *columns, **kwargs: operations.append(("create_table", name)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table_name, columns: operations.append(("create_index", name)),
    )

    migration.upgrade()

    assert operations == [
        ("create_index", "ix_youtube_channel_import_sessions_tenant_id"),
        ("create_index", "ix_youtube_channel_import_sessions_expiry"),
        ("create_index", "ix_youtube_channel_import_sessions_t_oauth_grant_id"),
        ("create_table", "youtube_channel_import_candidates"),
        ("create_index", "ix_youtube_channel_import_candidates_tenant_id"),
        ("create_index", "ix_youtube_channel_import_candidates_t_import_session_id"),
    ]
