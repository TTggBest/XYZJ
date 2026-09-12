"""Replace tenant business links with composite foreign keys."""

from dataclasses import dataclass

from alembic import op
import sqlalchemy as sa


revision = "d9f2a5b0c498"
down_revision = "c8e1f4a9b387"
branch_labels = None
depends_on = None


FOREIGN_KEY_BATCHES = (
    ("channel", (
        ('channel_analysis_evidence', 'report_id', 'channel_analysis_reports', 'CASCADE', 'CASCADE'),
        ('channel_analysis_keyword_scores', 'report_id', 'channel_analysis_reports', 'CASCADE', 'CASCADE'),
        ('channel_analysis_reports', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_analysis_topic_scores', 'report_id', 'channel_analysis_reports', 'CASCADE', 'CASCADE'),
        ('channel_audience_profiles', 'report_id', 'channel_analysis_reports', 'CASCADE', 'CASCADE'),
        ('channel_dna_signals', 'dna_version_id', 'channel_dna_versions', 'CASCADE', 'CASCADE'),
        ('channel_dna_versions', 'analysis_report_id', 'channel_analysis_reports', 'RESTRICT', 'SET NULL'),
        ('channel_dna_versions', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_initialization_drafts', 'applied_dna_version_id', 'channel_dna_versions', 'RESTRICT', 'SET NULL'),
        ('channel_initialization_drafts', 'applied_report_id', 'channel_analysis_reports', 'RESTRICT', 'SET NULL'),
        ('channel_initialization_drafts', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_keywords', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_logo_profiles', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_pinned_comment_templates', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_strategy_recommendations', 'report_id', 'channel_analysis_reports', 'CASCADE', 'CASCADE'),
    )),
    ("drama_schedule", (
        ('channel_community_slots', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_community_slots', 'publish_slot_id', 'channel_publish_slots', 'CASCADE', 'CASCADE'),
        ('channel_playlists', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_publish_slots', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_schedule_entries', 'channel_dna_version_id', 'channel_dna_versions', 'RESTRICT', 'SET NULL'),
        ('channel_schedule_entries', 'channel_id', 'channels', 'RESTRICT', 'RESTRICT'),
        ('channel_schedule_entries', 'drama_id', 'dramas', 'RESTRICT', 'RESTRICT'),
        ('channel_schedule_entries', 'playlist_id', 'channel_playlists', 'RESTRICT', 'SET NULL'),
        ('channel_schedule_entries', 'publish_slot_id', 'channel_publish_slots', 'RESTRICT', 'RESTRICT'),
        ('channel_schedule_entries', 'replaced_by_schedule_id', 'channel_schedule_entries', 'RESTRICT', 'SET NULL'),
        ('drama_aliases', 'drama_id', 'dramas', 'CASCADE', 'CASCADE'),
        ('drama_core_terms', 'drama_id', 'dramas', 'CASCADE', 'CASCADE'),
        ('drama_production_states', 'drama_id', 'dramas', 'CASCADE', 'CASCADE'),
        ('drama_translations', 'drama_id', 'dramas', 'CASCADE', 'CASCADE'),
        ('schedule_candidates', 'drama_id', 'dramas', 'RESTRICT', 'RESTRICT'),
        ('schedule_candidates', 'schedule_id', 'channel_schedule_entries', 'CASCADE', 'CASCADE'),
        ('schedule_change_history', 'new_drama_id', 'dramas', 'RESTRICT', 'SET NULL'),
        ('schedule_change_history', 'old_drama_id', 'dramas', 'RESTRICT', 'SET NULL'),
        ('schedule_change_history', 'schedule_id', 'channel_schedule_entries', 'CASCADE', 'CASCADE'),
    )),
    ("production_package", (
        ('operation_packages', 'batch_id', 'production_batches', 'RESTRICT', 'RESTRICT'),
        ('operation_packages', 'channel_dna_version_id', 'channel_dna_versions', 'RESTRICT', 'SET NULL'),
        ('operation_packages', 'channel_id', 'channels', 'RESTRICT', 'RESTRICT'),
        ('operation_packages', 'drama_id', 'dramas', 'RESTRICT', 'RESTRICT'),
        ('operation_packages', 'schedule_id', 'channel_schedule_entries', 'RESTRICT', 'RESTRICT'),
        ('operation_packages', 'work_order_id', 'work_orders', 'RESTRICT', 'RESTRICT'),
        ('operation_tasks', 'batch_id', 'production_batches', 'RESTRICT', 'RESTRICT'),
        ('operation_tasks', 'channel_id', 'channels', 'RESTRICT', 'RESTRICT'),
        ('operation_tasks', 'drama_id', 'dramas', 'RESTRICT', 'RESTRICT'),
        ('operation_tasks', 'playlist_id', 'channel_playlists', 'RESTRICT', 'SET NULL'),
        ('operation_tasks', 'publish_slot_id', 'channel_publish_slots', 'RESTRICT', 'RESTRICT'),
        ('operation_tasks', 'schedule_id', 'channel_schedule_entries', 'RESTRICT', 'RESTRICT'),
        ('package_artifacts', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_community_posts', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_creative_slots', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_descriptions', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_output_copy_states', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_playlist_assignments', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_playlist_assignments', 'playlist_id', 'channel_playlists', 'RESTRICT', 'RESTRICT'),
        ('package_similarity_checks', 'compared_package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_similarity_checks', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_titles', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_validation_results', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('production_node_runs', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('production_node_runs', 'work_order_id', 'work_orders', 'CASCADE', 'CASCADE'),
        ('task_events', 'task_id', 'operation_tasks', 'CASCADE', 'CASCADE'),
        ('work_orders', 'batch_id', 'production_batches', 'RESTRICT', 'RESTRICT'),
        ('work_orders', 'channel_dna_version_id', 'channel_dna_versions', 'RESTRICT', 'SET NULL'),
        ('work_orders', 'channel_id', 'channels', 'RESTRICT', 'RESTRICT'),
        ('work_orders', 'drama_id', 'dramas', 'RESTRICT', 'RESTRICT'),
        ('work_orders', 'playlist_id', 'channel_playlists', 'RESTRICT', 'SET NULL'),
        ('work_orders', 'publish_slot_id', 'channel_publish_slots', 'RESTRICT', 'RESTRICT'),
        ('work_orders', 'schedule_id', 'channel_schedule_entries', 'RESTRICT', 'RESTRICT'),
        ('work_orders', 'task_id', 'operation_tasks', 'RESTRICT', 'RESTRICT'),
    )),
    ("media_image", (
        ('channel_branding_assets', 'asset_id', 'media_assets', 'RESTRICT', 'RESTRICT'),
        ('channel_branding_assets', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('channel_profiles', 'avatar_asset_id', 'media_assets', 'RESTRICT', 'SET NULL'),
        ('channel_profiles', 'banner_asset_id', 'media_assets', 'RESTRICT', 'SET NULL'),
        ('channel_profiles', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('community_post_assets', 'asset_id', 'media_assets', 'RESTRICT', 'RESTRICT'),
        ('community_post_assets', 'community_post_id', 'package_community_posts', 'CASCADE', 'CASCADE'),
        ('image_processing_items', 'channel_id', 'channels', 'RESTRICT', 'SET NULL'),
        ('image_processing_items', 'drama_id', 'dramas', 'RESTRICT', 'SET NULL'),
        ('image_processing_items', 'package_id', 'operation_packages', 'RESTRICT', 'SET NULL'),
        ('image_processing_items', 'run_id', 'image_processing_runs', 'CASCADE', 'CASCADE'),
        ('image_processing_items', 'schedule_id', 'channel_schedule_entries', 'RESTRICT', 'SET NULL'),
        ('image_processing_runs', 'batch_id', 'production_batches', 'RESTRICT', 'RESTRICT'),
        ('media_assets', 'channel_id', 'channels', 'RESTRICT', 'SET NULL'),
        ('media_assets', 'operation_package_id', 'operation_packages', 'RESTRICT', 'SET NULL'),
        ('package_cover_variants', 'asset_id', 'media_assets', 'RESTRICT', 'SET NULL'),
        ('package_cover_variants', 'package_id', 'operation_packages', 'CASCADE', 'CASCADE'),
        ('package_cover_variants', 'title_id', 'package_titles', 'CASCADE', 'CASCADE'),
    )),
    ("oauth_youtube_integration", (
        ('account_channel_authorizations', 'account_id', 'google_accounts', 'RESTRICT', 'RESTRICT'),
        ('account_channel_authorizations', 'channel_id', 'channels', 'RESTRICT', 'RESTRICT'),
        ('account_channel_authorizations', 'oauth_grant_id', 'google_oauth_grants', 'RESTRICT', 'RESTRICT'),
        ('api_request_logs', 'authorization_id', 'account_channel_authorizations', 'RESTRICT', 'SET NULL'),
        ('api_request_logs', 'channel_id', 'channels', 'RESTRICT', 'SET NULL'),
        ('authorization_events', 'account_id', 'google_accounts', 'RESTRICT', 'SET NULL'),
        ('authorization_events', 'channel_id', 'channels', 'RESTRICT', 'SET NULL'),
        ('authorization_events', 'oauth_grant_id', 'google_oauth_grants', 'RESTRICT', 'SET NULL'),
        ('demo_data_entities', 'batch_id', 'demo_data_batches', 'CASCADE', 'CASCADE'),
        ('google_oauth_grant_scopes', 'grant_id', 'google_oauth_grants', 'CASCADE', 'CASCADE'),
        ('google_oauth_grants', 'account_id', 'google_accounts', 'RESTRICT', 'RESTRICT'),
        ('integration_credentials', 'integration_account_id', 'integration_accounts', 'CASCADE', 'CASCADE'),
        ('oauth_authorization_states', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('quota_usage_logs', 'account_id', 'google_accounts', 'RESTRICT', 'SET NULL'),
        ('quota_usage_logs', 'api_request_log_id', 'api_request_logs', 'CASCADE', 'CASCADE'),
        ('quota_usage_logs', 'channel_id', 'channels', 'RESTRICT', 'SET NULL'),
        ('sync_watermarks', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('youtube_analytics_breakdowns', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('youtube_analytics_breakdowns', 'video_id', 'youtube_videos', 'CASCADE', 'CASCADE'),
        ('youtube_channel_daily_metrics', 'channel_id', 'channels', 'CASCADE', 'CASCADE'),
        ('youtube_comment_replies', 'comment_id', 'youtube_comments', 'CASCADE', 'CASCADE'),
        ('youtube_comments', 'channel_id', 'channels', 'RESTRICT', 'RESTRICT'),
        ('youtube_comments', 'parent_comment_id', 'youtube_comments', 'CASCADE', 'CASCADE'),
        ('youtube_comments', 'video_id', 'youtube_videos', 'CASCADE', 'CASCADE'),
        ('youtube_playlist_order_history', 'membership_id', 'youtube_video_playlist_memberships', 'CASCADE', 'CASCADE'),
        ('youtube_playlist_order_history', 'playlist_id', 'channel_playlists', 'CASCADE', 'CASCADE'),
        ('youtube_playlist_order_history', 'video_id', 'youtube_videos', 'CASCADE', 'CASCADE'),
        ('youtube_video_daily_metrics', 'video_id', 'youtube_videos', 'CASCADE', 'CASCADE'),
        ('youtube_video_playlist_memberships', 'playlist_id', 'channel_playlists', 'RESTRICT', 'RESTRICT'),
        ('youtube_video_playlist_memberships', 'video_id', 'youtube_videos', 'CASCADE', 'CASCADE'),
        ('youtube_video_status_history', 'video_id', 'youtube_videos', 'CASCADE', 'CASCADE'),
        ('youtube_videos', 'channel_id', 'channels', 'RESTRICT', 'RESTRICT'),
        ('youtube_videos', 'drama_id', 'dramas', 'RESTRICT', 'SET NULL'),
        ('youtube_videos', 'operation_package_id', 'operation_packages', 'RESTRICT', 'SET NULL'),
        ('youtube_videos', 'schedule_id', 'channel_schedule_entries', 'RESTRICT', 'SET NULL'),
    )),
)


def _old_fk_name(table_name: str, column_name: str, parent_table: str) -> str:
    return f"fk_{table_name}_{column_name}_{parent_table}"

def _new_fk_name(table_name: str, column_name: str) -> str:
    return f"fk_{table_name}_t_{column_name}"

def _index_name(table_name: str, column_name: str) -> str:
    return f"ix_{table_name}_t_{column_name}"


@dataclass(frozen=True)
class Replacement:
    table_name: str
    column_name: str
    parent_table: str
    ondelete: str
    old_ondelete: str
    old_constraint_name: str
    index_exists: bool


def _plan_edge(edge, foreign_keys, indexes):
    table_name, column_name, parent_table, ondelete, old_ondelete = edge
    candidates = [
        row for row in foreign_keys
        if row["TABLE_NAME"] == table_name
        and row["REFERENCED_TABLE_NAME"] == parent_table
    ]
    old = [
        row for row in candidates
        if row["local_columns"] == column_name and row["remote_columns"] == "id"
    ]
    new = [
        row for row in candidates
        if row["local_columns"] == f"tenant_id,{column_name}"
        and row["remote_columns"] == "tenant_id,id"
    ]
    index_name = _index_name(table_name, column_name)
    index_columns = indexes.get((table_name, index_name))
    expected_index_columns = f"tenant_id,{column_name}"
    if index_columns not in (None, expected_index_columns):
        raise RuntimeError(f"{table_name}.{index_name} has unexpected columns {index_columns}")
    if len(new) == 1 and not old:
        row = new[0]
        if row["CONSTRAINT_NAME"] != _new_fk_name(table_name, column_name):
            raise RuntimeError(f"{table_name}.{column_name} composite FK has unexpected name")
        if row["DELETE_RULE"] != ondelete or index_columns != expected_index_columns:
            raise RuntimeError(f"{table_name}.{column_name} composite FK has unexpected definition")
        return None
    if len(old) == 1 and not new:
        row = old[0]
        if row["DELETE_RULE"] != old_ondelete:
            raise RuntimeError(f"{table_name}.{column_name} old FK has unexpected delete rule")
        if len(row["CONSTRAINT_NAME"]) > 64:
            raise RuntimeError(f"{table_name}.{column_name} old FK name exceeds MySQL limit")
        return Replacement(
            table_name, column_name, parent_table, ondelete, old_ondelete,
            row["CONSTRAINT_NAME"], index_columns is not None,
        )
    raise RuntimeError(
        f"{table_name}.{column_name} must have exactly one old or completed composite FK"
    )


def _replacement_plan(connection):
    schema = connection.scalar(sa.text("SELECT DATABASE()"))
    foreign_keys = list(connection.execute(sa.text("""
        SELECT k.TABLE_NAME, k.CONSTRAINT_NAME,
               GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION) AS local_columns,
               k.REFERENCED_TABLE_NAME,
               GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION) AS remote_columns,
               r.DELETE_RULE
        FROM information_schema.KEY_COLUMN_USAGE AS k
        JOIN information_schema.REFERENTIAL_CONSTRAINTS AS r
          ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA
         AND r.TABLE_NAME = k.TABLE_NAME
         AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME
        WHERE k.CONSTRAINT_SCHEMA = :schema AND k.REFERENCED_TABLE_NAME IS NOT NULL
        GROUP BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME, r.DELETE_RULE
    """), {"schema": schema}).mappings())
    index_rows = connection.execute(sa.text("""
        SELECT TABLE_NAME, INDEX_NAME,
               GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns_csv
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = :schema
        GROUP BY TABLE_NAME, INDEX_NAME
    """), {"schema": schema}).mappings()
    indexes = {
        (row["TABLE_NAME"], row["INDEX_NAME"]): row["columns_csv"]
        for row in index_rows
    }
    planned = []
    for _batch_name, edges in FOREIGN_KEY_BATCHES:
        for edge in edges:
            replacement = _plan_edge(edge, foreign_keys, indexes)
            if replacement is not None:
                planned.append(replacement)
    return planned


def _assert_parent_links_are_tenant_consistent(connection) -> None:
    for _batch_name, edges in FOREIGN_KEY_BATCHES:
        for table_name, column_name, parent_table, _ondelete, _old_ondelete in edges:
            mismatch = connection.execute(sa.text(
                f"SELECT child.{column_name} FROM {table_name} AS child "
                f"LEFT JOIN {parent_table} AS parent ON parent.id = child.{column_name} "
                f"WHERE child.{column_name} IS NOT NULL AND "
                "(child.tenant_id IS NULL OR parent.id IS NULL OR parent.tenant_id IS NULL "
                "OR child.tenant_id <> parent.tenant_id) LIMIT 1"
            )).first()
            if mismatch is not None:
                raise RuntimeError(
                    f"{table_name}.{column_name} has orphan or cross-tenant parent: {mismatch}"
                )

def upgrade() -> None:
    connection = op.get_bind()
    _assert_parent_links_are_tenant_consistent(connection)
    replacements = _replacement_plan(connection)
    for replacement in replacements:
        if not replacement.index_exists:
            op.create_index(
                _index_name(replacement.table_name, replacement.column_name),
                replacement.table_name,
                ["tenant_id", replacement.column_name],
            )
        op.drop_constraint(
            replacement.old_constraint_name,
            replacement.table_name,
            type_="foreignkey",
        )
        op.create_foreign_key(
            _new_fk_name(replacement.table_name, replacement.column_name),
            replacement.table_name,
            replacement.parent_table,
            ["tenant_id", replacement.column_name],
            ["tenant_id", "id"],
            ondelete=replacement.ondelete,
        )

def downgrade() -> None:
    for _batch_name, edges in reversed(FOREIGN_KEY_BATCHES):
        for table_name, column_name, parent_table, _ondelete, old_ondelete in reversed(edges):
            op.drop_constraint(_new_fk_name(table_name, column_name), table_name, type_="foreignkey")
            op.create_foreign_key(
                op.f(_old_fk_name(table_name, column_name, parent_table)), table_name, parent_table,
                [column_name], ["id"], ondelete=old_ondelete,
            )
            op.drop_index(_index_name(table_name, column_name), table_name=table_name)
