"""Scope OAuth authorization and the YouTube graph by tenant."""

from alembic import op
import sqlalchemy as sa


revision = "a6c9d2e7f165"
down_revision = "f5b8c1d6e054"
branch_labels = None
depends_on = None

ROOTS = ("google_accounts", "channels", "operation_packages", "dramas", "channel_schedule_entries", "channel_playlists")
OAUTH_COLUMNS = {
    "google_oauth_grants": ["account_id"],
    "google_oauth_grant_scopes": ["grant_id", "scope"],
    "account_channel_authorizations": ["account_id", "channel_id", "oauth_grant_id"],
    "authorization_events": ["account_id", "channel_id", "oauth_grant_id"],
}
YOUTUBE_COLUMNS = {
    "youtube_videos": ["channel_id", "operation_package_id", "drama_id", "schedule_id"],
    "youtube_video_playlist_memberships": ["video_id", "playlist_id"],
    "youtube_playlist_order_history": ["membership_id", "playlist_id", "video_id"],
    "youtube_video_status_history": ["video_id"],
    "youtube_comments": ["video_id", "channel_id", "parent_comment_id"],
    "youtube_comment_replies": ["comment_id"],
    "youtube_video_daily_metrics": ["video_id"],
    "youtube_analytics_breakdowns": ["channel_id", "video_id", "scope_type", "scope_entity_id"],
}
NEW_TABLES = {**OAUTH_COLUMNS, **YOUTUBE_COLUMNS}
EXISTING_COLUMNS = {
    "youtube_channel_daily_metrics": ["tenant_id", "channel_id"],
    "sync_watermarks": ["tenant_id", "channel_id"],
    "api_request_logs": ["tenant_id", "channel_id", "authorization_id"],
    "quota_usage_logs": ["tenant_id", "api_request_log_id", "channel_id", "account_id"],
}
PARENTS = {
    "google_oauth_grants": {"account_id": "google_accounts"},
    "google_oauth_grant_scopes": {"grant_id": "google_oauth_grants"},
    "account_channel_authorizations": {
        "account_id": "google_accounts", "channel_id": "channels",
        "oauth_grant_id": "google_oauth_grants",
    },
    "authorization_events": {
        "account_id": "google_accounts", "channel_id": "channels",
        "oauth_grant_id": "google_oauth_grants",
    },
    "youtube_videos": {
        "channel_id": "channels", "operation_package_id": "operation_packages",
        "drama_id": "dramas", "schedule_id": "channel_schedule_entries",
    },
    "youtube_video_playlist_memberships": {
        "video_id": "youtube_videos", "playlist_id": "channel_playlists",
    },
    "youtube_playlist_order_history": {
        "membership_id": "youtube_video_playlist_memberships",
        "playlist_id": "channel_playlists", "video_id": "youtube_videos",
    },
    "youtube_video_status_history": {"video_id": "youtube_videos"},
    "youtube_comments": {
        "video_id": "youtube_videos", "channel_id": "channels",
        "parent_comment_id": "youtube_comments",
    },
    "youtube_comment_replies": {"comment_id": "youtube_comments"},
    "youtube_video_daily_metrics": {"video_id": "youtube_videos"},
    "youtube_analytics_breakdowns": {
        "channel_id": "channels", "video_id": "youtube_videos",
    },
    "youtube_channel_daily_metrics": {"channel_id": "channels"},
    "sync_watermarks": {"channel_id": "channels"},
    "api_request_logs": {
        "channel_id": "channels", "authorization_id": "account_channel_authorizations",
    },
    "quota_usage_logs": {
        "api_request_log_id": "api_request_logs", "channel_id": "channels",
        "account_id": "google_accounts",
    },
}
OPTIONAL = {
    "authorization_events": {"account_id", "channel_id", "oauth_grant_id"},
    "youtube_videos": {"operation_package_id", "drama_id", "schedule_id"},
    "youtube_comments": {"parent_comment_id"},
    "youtube_analytics_breakdowns": {"video_id"},
    "api_request_logs": {"channel_id", "authorization_id"},
    "quota_usage_logs": {"channel_id", "account_id"},
}


def load_rows(connection):
    rows = {
        table: list(connection.execute(sa.text(f"SELECT id, tenant_id FROM {table}")).mappings())
        for table in ROOTS
    }
    for table, columns in NEW_TABLES.items():
        key = "" if table == "google_oauth_grant_scopes" else "id, "
        rows[table] = list(connection.execute(sa.text(
            f"SELECT {key}{', '.join(columns)} FROM {table}"
        )).mappings())
    for table, columns in EXISTING_COLUMNS.items():
        rows[table] = list(connection.execute(sa.text(
            f"SELECT id, {', '.join(columns)} FROM {table}"
        )).mappings())
    return rows


def validate_owners(rows):
    owners = {}
    for table in ROOTS:
        owners[table] = {}
        for row in rows[table]:
            if not row["tenant_id"]:
                raise RuntimeError(f"{table}:{row['id']} missing tenant")
            owners[table][row["id"]] = row["tenant_id"]

    for table in (*NEW_TABLES, *EXISTING_COLUMNS):
        owners[table] = {}
        for row in rows[table]:
            key = (row["grant_id"], row["scope"]) if table == "google_oauth_grant_scopes" else row["id"]
            candidates = set()
            if table in EXISTING_COLUMNS:
                if not row["tenant_id"]:
                    raise RuntimeError(f"{table}:{key} missing tenant")
                candidates.add(row["tenant_id"])
            for column, parent in PARENTS[table].items():
                parent_id = row[column]
                if parent_id is None and column in OPTIONAL.get(table, set()):
                    continue
                tenant_id = owners[parent].get(parent_id)
                if not tenant_id:
                    raise RuntimeError(f"{table}:{key} {column} has no derivable tenant")
                candidates.add(tenant_id)
            if not candidates:
                raise RuntimeError(f"{table}:{key} has no derivable tenant")
            if len(candidates) != 1:
                raise RuntimeError(f"{table}:{key} parent tenant mismatch")
            tenant_id = candidates.pop()
            if table == "youtube_analytics_breakdowns":
                expected_scope = row["channel_id"] if row["scope_type"] == "channel" else row["video_id"]
                if row["scope_entity_id"] != expected_scope:
                    raise RuntimeError(f"{table}:{key} scope parent mismatch")
            owners[table][key] = tenant_id
    return owners


def upgrade():
    connection = op.get_bind()
    # MySQL DDL commits implicitly; validate every strong parent before the first ALTER/CREATE.
    owners = validate_owners(load_rows(connection))
    for table in NEW_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        if table == "google_oauth_grant_scopes":
            for (grant_id, scope), tenant_id in owners[table].items():
                connection.execute(sa.text(
                    "UPDATE google_oauth_grant_scopes SET tenant_id=:tenant_id "
                    "WHERE grant_id=:grant_id AND scope=:scope"
                ), {"tenant_id": tenant_id, "grant_id": grant_id, "scope": scope})
        elif owners[table]:
            connection.execute(sa.text(f"UPDATE {table} SET tenant_id=:tenant_id WHERE id=:id"), [
                {"id": row_id, "tenant_id": tenant_id}
                for row_id, tenant_id in owners[table].items()
            ])

    op.create_table(
        "oauth_authorization_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("opaque_state", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("opaque_state", name="uq_oauth_authorization_states_opaque"),
    )
    op.create_index("ix_oauth_authorization_states_tenant_id", "oauth_authorization_states", ["tenant_id"])
    op.create_index("ix_oauth_authorization_states_expiry", "oauth_authorization_states", ["expires_at", "consumed_at"])


def downgrade():
    op.drop_index("ix_oauth_authorization_states_expiry", table_name="oauth_authorization_states")
    op.drop_index("ix_oauth_authorization_states_tenant_id", table_name="oauth_authorization_states")
    op.drop_table("oauth_authorization_states")
    for table in reversed(NEW_TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
