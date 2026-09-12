"""Scope business keys and add tenant parent candidate keys."""

from alembic import op
import sqlalchemy as sa


revision = "c8e1f4a9b387"
down_revision = "b7d0e3f8a276"
branch_labels = None
depends_on = None


PARENT_TABLES = (
    "account_channel_authorizations",
    "api_request_logs",
    "channel_analysis_reports",
    "channel_dna_versions",
    "channel_playlists",
    "channel_publish_slots",
    "channel_schedule_entries",
    "channels",
    "demo_data_batches",
    "dramas",
    "google_accounts",
    "google_oauth_grants",
    "image_processing_runs",
    "integration_accounts",
    "media_assets",
    "operation_packages",
    "operation_tasks",
    "package_community_posts",
    "package_titles",
    "production_batches",
    "work_orders",
    "youtube_comments",
    "youtube_video_playlist_memberships",
    "youtube_videos",
)

# These include keys already scoped by earlier graph revisions. Rechecking every
# promised business key before the first ALTER keeps the migration all-or-stop.
DUPLICATE_KEYS = (
    ("dramas", ("tenant_id", "drama_code")),
    ("dramas", ("tenant_id", "normalized_title")),
    ("drama_aliases", ("tenant_id", "normalized_alias")),
    ("production_batches", ("tenant_id", "batch_number")),
    ("integration_accounts", ("tenant_id", "integration_id", "account_key")),
    ("image_workspace_settings", ("tenant_id",)),
    ("channel_drama_types", ("tenant_id", "code")),
    ("channel_drama_types", ("tenant_id", "name")),
    ("channel_schedule_entries", ("tenant_id", "idempotency_key")),
    ("operation_tasks", ("tenant_id", "idempotency_key")),
    ("production_node_runs", ("tenant_id", "idempotency_key")),
    ("api_request_logs", ("tenant_id", "request_key")),
    ("audit_events", ("tenant_id", "idempotency_key")),
    ("media_assets", ("tenant_id", "storage_provider", "storage_key")),
)

UNIQUE_CHANGES = (
    ("dramas", "uq_dramas_drama_code", "uq_dramas_tenant_drama_code", ("tenant_id", "drama_code"), ("drama_code",)),
    ("drama_aliases", "uq_drama_aliases_normalized_alias", "uq_drama_aliases_tenant_alias", ("tenant_id", "normalized_alias"), ("normalized_alias",)),
    ("channel_drama_types", "uq_channel_drama_types_code", "uq_channel_drama_types_tenant_code", ("tenant_id", "code"), ("code",)),
    ("channel_drama_types", "uq_channel_drama_types_name", "uq_channel_drama_types_tenant_name", ("tenant_id", "name"), ("name",)),
    ("channel_schedule_entries", "uq_channel_schedule_entries_idempotency_key", "uq_schedule_entries_tenant_idempotency", ("tenant_id", "idempotency_key"), ("idempotency_key",)),
    ("production_node_runs", "uq_production_node_runs_idempotency_key", "uq_production_node_runs_tenant_idempotency", ("tenant_id", "idempotency_key"), ("idempotency_key",)),
    ("api_request_logs", "uq_api_request_logs_request_key", "uq_api_request_logs_tenant_request", ("tenant_id", "request_key"), ("request_key",)),
    ("audit_events", "uq_audit_events_idempotency_key", "uq_audit_events_tenant_idempotency", ("tenant_id", "idempotency_key"), ("idempotency_key",)),
    ("media_assets", "uq_media_assets_storage_location", "uq_media_assets_tenant_storage", ("tenant_id", "storage_provider", "storage_key"), ("storage_provider", "storage_key")),
)


def _assert_no_duplicate_business_keys(connection) -> None:
    for table_name, columns in DUPLICATE_KEYS:
        non_null = " AND ".join(f"{column} IS NOT NULL" for column in columns)
        column_sql = ", ".join(columns)
        duplicate = connection.execute(sa.text(
            f"SELECT {column_sql} FROM {table_name} "
            f"WHERE {non_null} GROUP BY {column_sql} HAVING COUNT(*) > 1 LIMIT 1"
        )).first()
        if duplicate is not None:
            raise RuntimeError(f"{table_name} duplicate tenant business key: {duplicate}")


def upgrade() -> None:
    _assert_no_duplicate_business_keys(op.get_bind())
    for table_name in PARENT_TABLES:
        op.create_unique_constraint(
            f"uq_{table_name}_tenant_id_id", table_name, ["tenant_id", "id"]
        )
    for table_name, old_name, new_name, columns, _old_columns in UNIQUE_CHANGES:
        op.drop_constraint(op.f(old_name), table_name, type_="unique")
        op.create_unique_constraint(new_name, table_name, list(columns))


def downgrade() -> None:
    for table_name, old_name, new_name, _columns, old_columns in reversed(UNIQUE_CHANGES):
        op.drop_constraint(new_name, table_name, type_="unique")
        op.create_unique_constraint(op.f(old_name), table_name, list(old_columns))
    for table_name in reversed(PARENT_TABLES):
        op.drop_constraint(f"uq_{table_name}_tenant_id_id", table_name, type_="unique")
