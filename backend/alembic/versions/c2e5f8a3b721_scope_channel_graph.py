"""Scope the channel graph after validating every strong parent chain.

Revision ID: c2e5f8a3b721
Revises: b1d4e7f2a610
"""
from alembic import op
import sqlalchemy as sa


revision = "c2e5f8a3b721"
down_revision = "b1d4e7f2a610"
branch_labels = None
depends_on = None

# The first parent establishes ownership. Remaining references must agree.
# Reports precede their children; DNA precedes drafts and schedules.
PARENTS = {
    "channel_profiles": {"channel_id": "channels", "avatar_asset_id": "media_assets", "banner_asset_id": "media_assets"},
    "channel_pinned_comment_templates": {"channel_id": "channels"},
    "channel_branding_assets": {"channel_id": "channels", "asset_id": "media_assets"},
    "channel_keywords": {"channel_id": "channels"},
    "channel_analysis_reports": {"channel_id": "channels"},
    "channel_analysis_topic_scores": {"report_id": "channel_analysis_reports"},
    "channel_analysis_keyword_scores": {"report_id": "channel_analysis_reports"},
    "channel_audience_profiles": {"report_id": "channel_analysis_reports"},
    "channel_strategy_recommendations": {"report_id": "channel_analysis_reports"},
    "channel_analysis_evidence": {"report_id": "channel_analysis_reports"},
    "channel_dna_versions": {"channel_id": "channels", "analysis_report_id": "channel_analysis_reports"},
    "channel_dna_signals": {"dna_version_id": "channel_dna_versions"},
    "channel_initialization_drafts": {"channel_id": "channels", "applied_report_id": "channel_analysis_reports", "applied_dna_version_id": "channel_dna_versions"},
    "channel_logo_profiles": {"channel_id": "channels"},
    "channel_playlists": {"channel_id": "channels"},
    "channel_publish_slots": {"channel_id": "channels"},
    "channel_community_slots": {"channel_id": "channels", "publish_slot_id": "channel_publish_slots"},
    "channel_schedule_entries": {
        "channel_id": "channels", "drama_id": "dramas", "channel_dna_version_id": "channel_dna_versions",
        "playlist_id": "channel_playlists", "publish_slot_id": "channel_publish_slots",
        "replaced_by_schedule_id": "channel_schedule_entries",
    },
    "sync_watermarks": {"channel_id": "channels"},
    "youtube_channel_daily_metrics": {"channel_id": "channels"},
}
REQUIRED_PARENTS = {("channel_branding_assets", "asset_id"),
                    ("channel_schedule_entries", "drama_id"),
                    ("channel_schedule_entries", "publish_slot_id")}


def _validated_owners(connection):
    owners = {}
    for name in ("channels", "dramas", "media_assets"):
        owners[name] = dict(connection.execute(sa.text(f"SELECT id, tenant_id FROM {name}")).all())
    rows_by_table = {}
    for name, parents in PARENTS.items():
        rows = connection.execute(sa.text(f"SELECT id, {', '.join(parents)} FROM {name}")).mappings().all()
        rows_by_table[name] = rows
        column, parent = next(iter(parents.items()))
        owners[name] = {}
        for row in rows:
            tenant_id = owners[parent].get(row[column])
            if not tenant_id:
                raise RuntimeError(f"{name}:{row['id']} {column} has no derivable tenant")
            owners[name][row["id"]] = tenant_id
    # Validate before MySQL performs any non-transactional ALTER TABLE. This
    # second pass also resolves references to later rows and schedule replacements.
    for name, parents in PARENTS.items():
        for row in rows_by_table[name]:
            for column, parent in parents.items():
                parent_id = row[column]
                if parent_id is None and (name, column) not in REQUIRED_PARENTS:
                    continue
                tenant_id = owners[parent].get(parent_id)
                if not tenant_id or tenant_id != owners[name][row["id"]]:
                    raise RuntimeError(f"{name}:{row['id']} {column} parent tenant mismatch or missing")
    return owners


def upgrade():
    connection = op.get_bind()
    owners = _validated_owners(connection)
    for name in PARENTS:
        op.add_column(name, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])
        if owners[name]:
            connection.execute(
                sa.text(f"UPDATE {name} SET tenant_id = :tenant_id WHERE id = :id"),
                [{"id": row_id, "tenant_id": tenant_id} for row_id, tenant_id in owners[name].items()],
            )


def downgrade():
    for name in reversed(PARENTS):
        op.drop_index(f"ix_{name}_tenant_id", table_name=name)
        op.drop_column(name, "tenant_id")
