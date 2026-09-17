"""Add YouTube channel import sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0d7a4c9e12f6"
down_revision = "d9f2a5b0c498"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    unique_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("google_accounts")
    }
    if "uq_google_accounts_google_email" in unique_names:
        op.drop_constraint(
            "uq_google_accounts_google_email", "google_accounts", type_="unique",
        )
    if "uq_google_accounts_tenant_email" not in unique_names:
        op.create_unique_constraint(
            "uq_google_accounts_tenant_email",
            "google_accounts",
            ["tenant_id", "google_email"],
        )

    table_names = set(inspector.get_table_names())
    if "youtube_channel_import_sessions" not in table_names:
        op.create_table(
            "youtube_channel_import_sessions",
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("auth_session_id", sa.String(36), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("oauth_grant_id", sa.String(36), nullable=True),
            sa.Column("opaque_state", sa.String(128), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending_oauth", comment="导入会话状态"),
            sa.Column("expires_at", sa.DateTime(), nullable=False, comment="会话过期时间"),
            sa.Column("consumed_at", sa.DateTime(), comment="OAuth回调完成时间"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "status IN ('pending_oauth','ready','committed','cancelled','expired')",
                name="ck_youtube_channel_import_sessions_valid_status",
            ),
            sa.UniqueConstraint("opaque_state", name="uq_youtube_channel_import_sessions_state"),
            sa.UniqueConstraint("tenant_id", "id", name="uq_youtube_channel_import_sessions_tenant_id_id"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "oauth_grant_id"],
                ["google_oauth_grants.tenant_id", "google_oauth_grants.id"],
                name="fk_youtube_channel_import_sessions_t_oauth_grant_id",
                ondelete="CASCADE",
            ),
        )
        session_index_names = set()
    else:
        session_index_names = {
            index["name"] for index in inspector.get_indexes("youtube_channel_import_sessions")
        }
    for name, columns in (
        ("ix_youtube_channel_import_sessions_tenant_id", ["tenant_id"]),
        ("ix_youtube_channel_import_sessions_expiry", ["status", "expires_at"]),
        ("ix_youtube_channel_import_sessions_t_oauth_grant_id", ["tenant_id", "oauth_grant_id"]),
    ):
        if name not in session_index_names:
            op.create_index(name, "youtube_channel_import_sessions", columns)

    if "youtube_channel_import_candidates" not in table_names:
        op.create_table(
            "youtube_channel_import_candidates",
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("import_session_id", sa.String(36), nullable=False, comment="所属导入会话ID"),
            sa.Column("youtube_channel_id", sa.String(64), nullable=False, comment="YouTube频道ID"),
            sa.Column("title", sa.String(255), nullable=False, comment="YouTube频道名称"),
            sa.Column("description", sa.Text(), comment="YouTube频道说明"),
            sa.Column("avatar_url", sa.String(1000), comment="YouTube频道头像地址"),
            sa.Column("custom_url", sa.String(500), comment="YouTube频道自定义地址"),
            sa.Column("youtube_country_code", sa.String(2), comment="YouTube登记国家代码"),
            sa.Column("youtube_default_language", sa.String(20), comment="YouTube登记默认语言"),
            sa.Column("uploads_playlist_id", sa.String(64), comment="YouTube上传播放列表ID"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "tenant_id", "import_session_id", "youtube_channel_id",
                name="uq_youtube_import_candidates_session_channel",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "import_session_id"],
                ["youtube_channel_import_sessions.tenant_id", "youtube_channel_import_sessions.id"],
                name="fk_youtube_channel_import_candidates_t_import_session_id",
                ondelete="CASCADE",
            ),
        )
        candidate_index_names = set()
    else:
        candidate_index_names = {
            index["name"] for index in inspector.get_indexes("youtube_channel_import_candidates")
        }
    for name, columns in (
        ("ix_youtube_channel_import_candidates_tenant_id", ["tenant_id"]),
        ("ix_youtube_channel_import_candidates_t_import_session_id", ["tenant_id", "import_session_id"]),
    ):
        if name not in candidate_index_names:
            op.create_index(name, "youtube_channel_import_candidates", columns)

def downgrade():
    op.drop_table("youtube_channel_import_candidates")
    op.drop_table("youtube_channel_import_sessions")
    op.drop_constraint(
        "uq_google_accounts_tenant_email", "google_accounts", type_="unique",
    )
    op.create_unique_constraint(
        "uq_google_accounts_google_email", "google_accounts", ["google_email"],
    )
