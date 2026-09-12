"""Scope production and package records after validating every strong parent.

Revision ID: e4a7b0c5d943
Revises: d3f6a9b4c832
"""
from alembic import op
import sqlalchemy as sa

revision = "e4a7b0c5d943"
down_revision = "d3f6a9b4c832"
branch_labels = None
depends_on = None

ROOTS = ("production_batches", "channels", "dramas")
EXISTING_PARENTS = {
    "channel_dna_versions": {"channel_id": "channels"},
    "channel_publish_slots": {"channel_id": "channels"},
    "channel_playlists": {"channel_id": "channels"},
    "channel_schedule_entries": {
        "channel_id": "channels", "drama_id": "dramas",
        "publish_slot_id": "channel_publish_slots", "playlist_id": "channel_playlists",
        "channel_dna_version_id": "channel_dna_versions",
    },
}
PARENTS = {
    "operation_tasks": {
        "batch_id": "production_batches", "channel_id": "channels", "drama_id": "dramas",
        "schedule_id": "channel_schedule_entries", "publish_slot_id": "channel_publish_slots",
        "playlist_id": "channel_playlists",
    },
    "task_events": {"task_id": "operation_tasks"},
    "work_orders": {
        "task_id": "operation_tasks", "batch_id": "production_batches",
        "schedule_id": "channel_schedule_entries", "channel_id": "channels", "drama_id": "dramas",
        "channel_dna_version_id": "channel_dna_versions", "publish_slot_id": "channel_publish_slots",
        "playlist_id": "channel_playlists",
    },
    "operation_packages": {
        "work_order_id": "work_orders", "batch_id": "production_batches",
        "schedule_id": "channel_schedule_entries", "channel_id": "channels", "drama_id": "dramas",
        "channel_dna_version_id": "channel_dna_versions",
    },
    "production_node_runs": {"work_order_id": "work_orders", "package_id": "operation_packages"},
    "package_titles": {"package_id": "operation_packages"},
    "package_descriptions": {"package_id": "operation_packages"},
    "package_cover_variants": {
        "package_id": "operation_packages", "title_id": "package_titles", "asset_id": "media_assets",
    },
    "package_community_posts": {"package_id": "operation_packages"},
    "community_post_assets": {"community_post_id": "package_community_posts", "asset_id": "media_assets"},
    "package_playlist_assignments": {"package_id": "operation_packages", "playlist_id": "channel_playlists"},
    "package_creative_slots": {"package_id": "operation_packages"},
    "package_artifacts": {"package_id": "operation_packages"},
    "package_validation_results": {"package_id": "operation_packages"},
    "package_similarity_checks": {"package_id": "operation_packages", "compared_package_id": "operation_packages"},
    "package_output_copy_states": {"package_id": "operation_packages"},
}
MEDIA_PARENTS = {"channel_id": "channels", "operation_package_id": "operation_packages"}
OPTIONAL = {
    "channel_schedule_entries": {"playlist_id", "channel_dna_version_id"},
    "operation_tasks": {"batch_id", "schedule_id", "publish_slot_id", "playlist_id"},
    "work_orders": {"batch_id", "schedule_id", "channel_dna_version_id", "publish_slot_id", "playlist_id"},
    "operation_packages": {"batch_id", "schedule_id", "channel_dna_version_id"},
    "package_cover_variants": {"asset_id"},
    "media_assets": set(MEDIA_PARENTS),
}
EVENT_PARENTS = {
    "operation_task": "operation_tasks", "work_order": "work_orders",
    "operation_package": "operation_packages", "production_node_run": "production_node_runs",
}
COPY_PARENTS = {
    "title": "package_titles", "cover": "package_cover_variants", "description": "package_descriptions",
    "community_text": "package_community_posts", "community_image": "package_community_posts",
}


def load_rows(connection):
    columns = {name: ["tenant_id"] for name in ROOTS}
    columns.update({name: ["tenant_id", *parents] for name, parents in EXISTING_PARENTS.items()})
    columns.update({name: list(parents) for name, parents in PARENTS.items()})
    columns["package_output_copy_states"].extend(["output_type", "output_id"])
    columns["media_assets"] = ["tenant_id", *MEDIA_PARENTS]
    columns["system_events"] = ["tenant_id", "entity_type", "entity_id"]
    return {name: list(connection.execute(sa.text(
        f"SELECT id, {', '.join(fields)} FROM {name}"
    )).mappings()) for name, fields in columns.items()}


def validate_owners(rows):
    """Derive one owner per row, refusing null, orphaned or conflicting parents."""
    owners = {}

    def validate(name, parents, *, existing=False):
        owners[name] = {}
        for row in rows[name]:
            tenant_ids = set()
            if existing:
                if not row["tenant_id"]:
                    raise RuntimeError(f"{name}:{row['id']} has no tenant")
                tenant_ids.add(row["tenant_id"])
            for column, parent in parents.items():
                if row[column] is None and column in OPTIONAL.get(name, set()):
                    continue
                tenant_id = owners[parent].get(row[column])
                if not tenant_id:
                    raise RuntimeError(f"{name}:{row['id']} {column} has no derivable tenant")
                tenant_ids.add(tenant_id)
            if len(tenant_ids) != 1:
                raise RuntimeError(f"{name}:{row['id']} parent tenant mismatch or missing")
            owners[name][row["id"]] = tenant_ids.pop()

    for name in ROOTS:
        validate(name, {}, existing=True)
    for name, parents in EXISTING_PARENTS.items():
        validate(name, parents, existing=True)
    for name, parents in PARENTS.items():
        validate(name, parents)
        if name == "operation_packages":
            # Media already has an owner. Validate both links before cover/post
            # children consume it; never overwrite a media owner's conflict.
            validate("media_assets", MEDIA_PARENTS, existing=True)
    for row in rows["package_output_copy_states"]:
        parent = COPY_PARENTS.get(row["output_type"])
        tenant_id = owners[parent].get(row["output_id"]) if parent else None
        if not tenant_id or owners["package_output_copy_states"][row["id"]] != tenant_id:
            raise RuntimeError(f"package_output_copy_states:{row['id']} output parent tenant mismatch or missing")
    owners["system_events"] = {}
    for row in rows["system_events"]:
        parent = EVENT_PARENTS.get(row["entity_type"])
        if parent is None:
            continue  # Other business event graphs are handled by their tasks.
        tenant_id = owners[parent].get(row["entity_id"])
        if not tenant_id or row["tenant_id"] != tenant_id:
            raise RuntimeError(f"system_events:{row['id']} parent tenant mismatch or missing")
        owners["system_events"][row["id"]] = tenant_id
    return owners


def upgrade():
    connection = op.get_bind()
    # MySQL ALTER TABLE commits implicitly: reject the whole graph before DDL.
    owners = validate_owners(load_rows(connection))
    for name in PARENTS:
        op.add_column(name, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])
        if owners[name]:
            connection.execute(sa.text(f"UPDATE {name} SET tenant_id=:tenant_id WHERE id=:id"),
                [{"id": row_id, "tenant_id": tenant_id} for row_id, tenant_id in owners[name].items()])


def downgrade():
    for name in reversed(PARENTS):
        op.drop_index(f"ix_{name}_tenant_id", table_name=name)
        op.drop_column(name, "tenant_id")
