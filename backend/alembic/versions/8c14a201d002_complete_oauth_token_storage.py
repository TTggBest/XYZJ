"""Complete token storage after joining local and cloud import histories.

Cloud installations already have this table; local installations do not.
Existing authorizations must be retained on upgrade and rollback.
"""

from alembic import op
import sqlalchemy as sa

revision = "8c14a201d002"
down_revision = "7b14a201d001"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "oauth_token_secrets" not in inspector.get_table_names():
        op.create_table(
            "oauth_token_secrets",
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("oauth_grant_id", sa.String(36), nullable=False, comment="Google OAuth授权ID"),
            sa.Column("encrypted_payload", sa.Text(), nullable=False, comment="加密后的OAuth令牌"),
            sa.Column("expires_at", sa.DateTime(), comment="令牌预计失效时间"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "oauth_grant_id", name="uq_oauth_token_secrets_tenant_grant"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "oauth_grant_id"],
                ["google_oauth_grants.tenant_id", "google_oauth_grants.id"],
                name="fk_oauth_token_secrets_t_oauth_grant_id",
                ondelete="CASCADE",
            ),
        )
        index_names = set()
    else:
        index_names = {index["name"] for index in inspector.get_indexes("oauth_token_secrets")}
    # MySQL DDL can stop after CREATE TABLE; a retry must finish its indexes.
    for name, columns in (
        ("ix_oauth_token_secrets_tenant_id", ["tenant_id"]),
        ("ix_oauth_token_secrets_t_oauth_grant_id", ["tenant_id", "oauth_grant_id"]),
    ):
        if name not in index_names:
            op.create_index(name, "oauth_token_secrets", columns)


def downgrade():
    # Forward repair: this table may predate this revision in a cloud database.
    # Keep its authorization records rather than deleting existing credentials.
    pass
