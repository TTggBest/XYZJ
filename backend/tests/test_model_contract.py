import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from zhiju.models import Base
from zhiju.models.base import TenantOwnedMixin


TENANT_ROOT_TABLES = (
    "channels", "dramas", "production_batches", "google_accounts",
    "integration_accounts", "channel_drama_types", "image_workspace_settings",
    "demo_data_batches", "feishu_sync_runs", "media_assets", "audit_events",
    "system_events", "api_request_logs", "quota_usage_logs",
)


@pytest.mark.parametrize("table_name", TENANT_ROOT_TABLES)
def test_tenant_roots_have_nullable_indexed_ownership(table_name):
    table = Base.metadata.tables[table_name]
    assert "tenant_id" in table.c
    column = table.c.tenant_id
    assert column.nullable is True
    assert column.type.length == 36
    assert column.comment
    model = next(mapper.class_ for mapper in Base.registry.mappers if mapper.local_table is table)
    assert issubclass(model, TenantOwnedMixin)
    indexes = [index for index in table.indexes if list(index.columns) == [column]]
    assert len(indexes) == 1
    assert indexes[0].name == f"ix_{table_name}_tenant_id"
    assert indexes[0].unique is False
    dialect = mysql.dialect()
    ddl = str(CreateTable(table).compile(dialect=dialect))
    assert "tenant_id VARCHAR(36) NOT NULL" not in ddl
    assert f"CREATE INDEX ix_{table_name}_tenant_id ON {table_name} (tenant_id)" == str(
        CreateIndex(indexes[0]).compile(dialect=dialect)
    )
    for foreign_key in table.foreign_key_constraints:
        columns = list(foreign_key.columns)
        if len(columns) == 2 and columns[0].name == "tenant_id":
            assert foreign_key.name == f"fk_{table_name}_t_{columns[1].name}"
        else:
            assert len(columns) == 1
            assert foreign_key.name == (
                f"fk_{table_name}_{columns[0].name}_{foreign_key.referred_table.name}"
            )
        # MySQL truncates long convention-generated names to its 64-character limit.
        mysql_name = dialect.identifier_preparer.format_constraint(foreign_key)
        assert len(mysql_name.strip("`")) <= 64
        assert f"CONSTRAINT {mysql_name} FOREIGN KEY" in ddl


def test_foundation_tables_are_registered() -> None:
    assert {
        "devices",
        "google_accounts",
        "google_oauth_grants",
        "google_oauth_grant_scopes",
        "channels",
        "account_channel_authorizations",
        "authorization_events",
        "audit_events",
        "schema_comments",
        "media_assets",
        "channel_profiles",
        "channel_branding_assets",
        "channel_keywords",
        "channel_pinned_comment_templates",
        "channel_analysis_reports",
        "channel_analysis_topic_scores",
        "channel_analysis_keyword_scores",
        "channel_audience_profiles",
        "channel_strategy_recommendations",
        "channel_analysis_evidence",
        "channel_dna_versions",
        "channel_dna_signals",
        "integrations",
        "integration_accounts",
        "integration_credentials",
        "languages",
        "dramas",
        "drama_aliases",
        "drama_core_terms",
        "drama_translations",
        "channel_playlists",
        "channel_publish_slots",
        "channel_community_slots",
        "publish_cadence_template_slots",
        "channel_schedule_entries",
        "schedule_change_history",
        "schedule_candidates",
        "operation_tasks",
        "task_events",
        "work_orders",
        "operation_packages",
        "production_node_runs",
        "package_titles",
        "package_descriptions",
        "package_cover_variants",
        "package_community_posts",
        "community_post_assets",
        "package_playlist_assignments",
        "package_creative_slots",
        "package_artifacts",
        "package_validation_results",
        "package_similarity_checks",
        "package_output_copy_states",
        "system_events",
        "youtube_videos",
        "youtube_video_playlist_memberships",
        "youtube_playlist_order_history",
        "youtube_video_status_history",
        "youtube_comments",
        "youtube_comment_replies",
        "youtube_channel_daily_metrics",
        "youtube_video_daily_metrics",
        "youtube_analytics_breakdowns",
        "sync_watermarks",
        "api_request_logs",
        "quota_usage_logs",
        "skills",
        "skill_versions",
        "image_workspace_settings",
        "channel_logo_profiles",
        "image_processing_runs",
        "image_processing_items",
    }.issubset(Base.metadata.tables)


def test_every_foundation_column_has_a_chinese_comment() -> None:
    missing = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not column.comment:
                missing.append(f"{table.name}.{column.name}")
    assert missing == []


def test_tokens_are_not_database_columns() -> None:
    forbidden = {"access_token", "refresh_token", "password", "app_secret"}
    actual = {column.name for table in Base.metadata.sorted_tables for column in table.columns}
    assert forbidden.isdisjoint(actual)
