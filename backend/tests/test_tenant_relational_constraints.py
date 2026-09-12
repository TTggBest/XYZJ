from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql

from zhiju.models import Base


ROOT = Path(__file__).resolve().parents[2]

TENANT_BUSINESS_TABLES = frozenset(
    {
        "channel_drama_types", "image_workspace_settings", "integration_accounts",
        "integration_credentials", "google_accounts", "google_oauth_grants",
        "google_oauth_grant_scopes", "account_channel_authorizations",
        "authorization_events", "oauth_authorization_states", "feishu_sync_runs",
        "channels", "channel_profiles", "channel_initialization_drafts",
        "channel_pinned_comment_templates", "channel_branding_assets", "channel_keywords",
        "channel_analysis_reports", "channel_analysis_topic_scores",
        "channel_analysis_keyword_scores", "channel_audience_profiles",
        "channel_strategy_recommendations", "channel_analysis_evidence",
        "channel_dna_versions", "channel_dna_signals", "channel_logo_profiles",
        "channel_playlists", "channel_publish_slots", "channel_community_slots",
        "channel_schedule_entries", "sync_watermarks", "youtube_channel_daily_metrics",
        "dramas", "drama_aliases", "drama_core_terms", "drama_translations",
        "drama_production_states", "schedule_candidates", "schedule_change_history",
        "production_batches", "operation_tasks", "task_events", "work_orders",
        "operation_packages", "package_output_copy_states", "production_node_runs",
        "package_titles", "package_descriptions", "package_cover_variants",
        "package_community_posts", "community_post_assets", "package_playlist_assignments",
        "package_creative_slots", "package_artifacts", "package_validation_results",
        "package_similarity_checks", "system_events", "media_assets",
        "image_processing_runs", "image_processing_items", "youtube_videos",
        "youtube_video_playlist_memberships", "youtube_playlist_order_history",
        "youtube_video_status_history", "youtube_comments", "youtube_comment_replies",
        "youtube_video_daily_metrics", "youtube_analytics_breakdowns", "api_request_logs",
        "quota_usage_logs", "demo_data_batches", "demo_data_entities", "audit_events",
    }
)

TENANT_UNIQUE_KEYS = {
    "dramas": {("tenant_id", "drama_code"), ("tenant_id", "normalized_title")},
    "drama_aliases": {("tenant_id", "normalized_alias")},
    "production_batches": {("tenant_id", "batch_number")},
    "integration_accounts": {("tenant_id", "integration_id", "account_key")},
    "image_workspace_settings": {("tenant_id",)},
    "channel_drama_types": {("tenant_id", "code"), ("tenant_id", "name")},
    "channel_schedule_entries": {("tenant_id", "idempotency_key")},
    "operation_tasks": {("tenant_id", "idempotency_key")},
    "production_node_runs": {("tenant_id", "idempotency_key")},
    "api_request_logs": {("tenant_id", "request_key")},
    "audit_events": {("tenant_id", "idempotency_key")},
    "media_assets": {("tenant_id", "storage_provider", "storage_key")},
}


def _column_names(constraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def _unique_keys(table_name: str) -> set[tuple[str, ...]]:
    return {
        _column_names(constraint)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_each_tenant_parent_has_a_tenant_id_id_candidate_key():
    parents = {
        fk.referred_table.name
        for table_name in TENANT_BUSINESS_TABLES
        for fk in Base.metadata.tables[table_name].foreign_key_constraints
        if fk.referred_table.name in TENANT_BUSINESS_TABLES
    }
    assert parents
    for table_name in sorted(parents):
        assert ("tenant_id", "id") in _unique_keys(table_name), table_name


def test_every_business_parent_link_is_a_tenant_composite_foreign_key():
    seen = 0
    for table_name in sorted(TENANT_BUSINESS_TABLES):
        for fk in Base.metadata.tables[table_name].foreign_key_constraints:
            if fk.referred_table.name not in TENANT_BUSINESS_TABLES:
                continue
            seen += 1
            local_columns = _column_names(fk)
            remote_columns = tuple(element.column.name for element in fk.elements)
            assert local_columns[0] == "tenant_id", (table_name, local_columns)
            assert remote_columns == ("tenant_id", "id"), (table_name, local_columns)
            assert len(fk.name) <= 64
            assert fk.name.startswith("fk_")
            # MySQL SET NULL applies to every local FK column. It would erase
            # tenant ownership now and make Task 14's tenant_id NOT NULL impossible.
            assert fk.ondelete != "SET NULL", (table_name, local_columns)
    assert seen >= 100


@pytest.mark.parametrize(
    ("child", "column", "parent"),
    [
        ("drama_translations", "language_id", "languages"),
        ("integration_accounts", "integration_id", "integrations"),
        ("oauth_authorization_states", "user_id", "app_users"),
        ("oauth_authorization_states", "session_id", "auth_sessions"),
        ("authorization_events", "device_id", "devices"),
    ],
)
def test_global_directory_and_identity_links_remain_single_column(child, column, parent):
    matches = [
        fk for fk in Base.metadata.tables[child].foreign_key_constraints
        if _column_names(fk) == (column,) and fk.referred_table.name == parent
    ]
    assert len(matches) == 1


@pytest.mark.parametrize("table_name", sorted(TENANT_UNIQUE_KEYS))
def test_business_keys_are_unique_only_inside_a_tenant(table_name):
    actual = _unique_keys(table_name)
    assert TENANT_UNIQUE_KEYS[table_name] <= actual
    scoped_suffixes = {key[1:] for key in TENANT_UNIQUE_KEYS[table_name] if len(key) > 1}
    assert not ({key for key in actual if key in scoped_suffixes}), table_name


def test_mysql_constraint_and_index_names_fit_the_actual_identifier_limit():
    dialect = mysql.dialect()
    assert dialect.max_identifier_length == 255
    # MySQL itself limits identifiers to 64 characters even though SQLAlchemy's
    # generic dialect attribute is broader for modern server versions.
    for table_name in TENANT_BUSINESS_TABLES:
        table = Base.metadata.tables[table_name]
        for item in (*table.constraints, *table.indexes):
            if item.name is not None:
                assert len(str(item.name)) <= 64, (table_name, item.name)


def test_two_relational_revisions_form_the_only_head_chain():
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    revisions = {revision.revision: revision for revision in scripts.walk_revisions()}
    assert revisions["c8e1f4a9b387"].down_revision == "b7d0e3f8a276"
    assert revisions["d9f2a5b0c498"].down_revision == "c8e1f4a9b387"
    assert scripts.get_heads() == ["d9f2a5b0c498"]


def _revision_module(revision_id: str):
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(revision_id)
    assert revision is not None, f"missing revision {revision_id}"
    return revision.module


class _Rows:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class _Connection:
    def __init__(self, duplicate_on_call: int | None = None):
        self.queries = []
        self.duplicate_on_call = duplicate_on_call

    def execute(self, statement):
        self.queries.append(str(statement))
        row = ("duplicate",) if len(self.queries) == self.duplicate_on_call else None
        return _Rows(row)


class _Operations:
    def __init__(self, connection):
        self.connection = connection
        self.calls = []

    def get_bind(self):
        return self.connection

    def f(self, name):
        return name

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def test_unique_revision_checks_all_duplicate_keys_before_any_ddl(monkeypatch):
    migration = _revision_module("c8e1f4a9b387")
    connection = _Connection(duplicate_on_call=1)
    operations = _Operations(connection)
    monkeypatch.setattr(migration, "op", operations)

    with pytest.raises(RuntimeError, match="duplicate tenant business key"):
        migration.upgrade()

    assert len(connection.queries) == 1
    assert "GROUP BY tenant_id" in connection.queries[0]
    assert "HAVING COUNT(*) > 1" in connection.queries[0]
    assert operations.calls == []


def test_composite_revision_matches_the_model_graph_and_orders_index_before_fk(monkeypatch):
    migration = _revision_module("d9f2a5b0c498")
    expected = {
        (table_name, _column_names(fk)[1], fk.referred_table.name, fk.ondelete)
        for table_name in TENANT_BUSINESS_TABLES
        for fk in Base.metadata.tables[table_name].foreign_key_constraints
        if fk.referred_table.name in TENANT_BUSINESS_TABLES
    }
    actual = {
        edge[:4]
        for _batch_name, edges in migration.FOREIGN_KEY_BATCHES
        for edge in edges
    }
    assert actual == expected

    first_edge = migration.FOREIGN_KEY_BATCHES[0][1][0]
    table_name, column_name, parent_table, ondelete, old_ondelete = first_edge
    connection = _Connection()
    operations = _Operations(connection)
    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(
        migration,
        "_replacement_plan",
        lambda _connection: [
            migration.Replacement(
                table_name, column_name, parent_table, ondelete, old_ondelete,
                "actual_old_constraint_name", False,
            )
        ],
    )
    migration.upgrade()
    index_name = f"ix_{table_name}_t_{column_name}"
    fk_name = f"fk_{table_name}_t_{column_name}"
    assert [call[0] for call in operations.calls] == [
        "create_index", "drop_constraint", "create_foreign_key",
    ]
    assert operations.calls[0][1][0] == index_name
    assert operations.calls[1][1][0] == "actual_old_constraint_name"
    assert operations.calls[2][1][0] == fk_name
    assert len(index_name) <= 64
    assert len(fk_name) <= 64


def test_composite_revision_uses_actual_mysql_name_and_resumes_partial_ddl():
    migration = _revision_module("d9f2a5b0c498")
    edge = (
        "channel_initialization_drafts", "applied_dna_version_id",
        "channel_dna_versions", "RESTRICT", "SET NULL",
    )
    fk_rows = [{
        "TABLE_NAME": edge[0],
        "CONSTRAINT_NAME": "fk_channel_init_draft_dna",
        "local_columns": edge[1],
        "REFERENCED_TABLE_NAME": edge[2],
        "remote_columns": "id",
        "DELETE_RULE": edge[4],
    }]
    indexes = {(edge[0], f"ix_{edge[0]}_t_{edge[1]}"): f"tenant_id,{edge[1]}"}
    replacement = migration._plan_edge(edge, fk_rows, indexes)
    assert replacement.old_constraint_name == "fk_channel_init_draft_dna"
    assert replacement.index_exists is True


def test_composite_downgrade_only_replaces_foreign_keys_and_drops_owned_indexes(monkeypatch):
    migration = _revision_module("d9f2a5b0c498")
    operations = _Operations(_Connection())
    monkeypatch.setattr(migration, "op", operations)
    migration.downgrade()
    assert operations.connection.queries == []
    assert {call[0] for call in operations.calls} <= {
        "drop_constraint", "create_foreign_key", "drop_index",
    }
    assert all("tenant_id" not in call[1][:1] for call in operations.calls if call[0] == "drop_column")
