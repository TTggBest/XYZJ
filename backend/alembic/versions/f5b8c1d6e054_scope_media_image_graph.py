"""Scope image runs/items after checking batch, workspace and media ownership."""
from alembic import op
import sqlalchemy as sa

revision = "f5b8c1d6e054"
down_revision = "e4a7b0c5d943"
branch_labels = None
depends_on = None

COLUMNS = {
    "channels": ["tenant_id"], "dramas": ["tenant_id"], "production_batches": ["tenant_id"],
    "image_workspace_settings": ["tenant_id"],
    "channel_schedule_entries": ["tenant_id", "channel_id", "drama_id"],
    "operation_packages": ["tenant_id", "channel_id", "drama_id", "batch_id", "schedule_id"],
    "media_assets": ["tenant_id", "channel_id", "operation_package_id", "storage_key"],
    "image_processing_runs": ["batch_id"],
    "image_processing_items": ["run_id", "package_id", "channel_id", "drama_id", "schedule_id", "stored_path", "output_path"],
}
PARENTS = {
    "channel_schedule_entries": {"channel_id": "channels", "drama_id": "dramas"},
    "operation_packages": {"channel_id": "channels", "drama_id": "dramas", "batch_id": "production_batches", "schedule_id": "channel_schedule_entries"},
    "media_assets": {"channel_id": "channels", "operation_package_id": "operation_packages"},
    "image_processing_runs": {"batch_id": "production_batches"},
    "image_processing_items": {"run_id": "image_processing_runs", "package_id": "operation_packages", "channel_id": "channels", "drama_id": "dramas", "schedule_id": "channel_schedule_entries"},
}
OPTIONAL = {
    "operation_packages": {"batch_id", "schedule_id"},
    "media_assets": {"channel_id", "operation_package_id"},
    "image_processing_items": {"package_id", "channel_id", "drama_id", "schedule_id"},
}
NEW_TABLES = ("image_processing_runs", "image_processing_items")


def load_rows(connection):
    return {table: list(connection.execute(sa.text(
        f"SELECT id, {', '.join(columns)} FROM {table}"
    )).mappings()) for table, columns in COLUMNS.items()}


def validate_owners(rows):
    owners = {}
    by_id = {table: {row["id"]: row for row in values} for table, values in rows.items()}
    for table in COLUMNS:
        owners[table] = {}
        for row in rows[table]:
            candidates = set()
            if table not in NEW_TABLES:
                if not row["tenant_id"]:
                    raise RuntimeError(f"{table}:{row['id']} missing tenant")
                candidates.add(row["tenant_id"])
            for column, parent in PARENTS.get(table, {}).items():
                if row[column] is None and column in OPTIONAL.get(table, set()):
                    continue
                tenant = owners[parent].get(row[column])
                if not tenant:
                    raise RuntimeError(f"{table}:{row['id']} {column} has no derivable tenant")
                candidates.add(tenant)
            if len(candidates) != 1:
                raise RuntimeError(f"{table}:{row['id']} parent tenant mismatch")
            owners[table][row["id"]] = candidates.pop()

    workspace_tenants = list(owners["image_workspace_settings"].values())
    if len(set(workspace_tenants)) != len(workspace_tenants):
        raise RuntimeError("image_workspace_settings: duplicate tenant workspace")
    for run_id, tenant in owners["image_processing_runs"].items():
        if tenant not in workspace_tenants:
            raise RuntimeError(f"image_processing_runs:{run_id} missing tenant workspace")

    media_by_path = {}
    for media in rows["media_assets"]:
        media_by_path.setdefault(media["storage_key"], []).append(media)
    for item in rows["image_processing_items"]:
        tenant = owners["image_processing_items"][item["id"]]
        run = by_id["image_processing_runs"][item["run_id"]]
        package = by_id["operation_packages"].get(item["package_id"])
        if package:
            for column, expected in (("batch_id", run["batch_id"]), ("channel_id", item["channel_id"]),
                                     ("drama_id", item["drama_id"]), ("schedule_id", item["schedule_id"])):
                if package[column] is not None and expected is not None and package[column] != expected:
                    raise RuntimeError(f"image_processing_items:{item['id']} package parent tenant chain mismatch")
        for path in (item["stored_path"], item["output_path"]):
            for media in media_by_path.get(path, []):
                if media["tenant_id"] != tenant or any(
                    media[mcol] is not None and item[icol] is not None and media[mcol] != item[icol]
                    for mcol, icol in (("channel_id", "channel_id"), ("operation_package_id", "package_id"))
                ):
                    raise RuntimeError(f"image_processing_items:{item['id']} media parent tenant mismatch")
    return owners


def upgrade():
    connection = op.get_bind()
    # MySQL DDL commits implicitly, so validate every row before the first ALTER.
    owners = validate_owners(load_rows(connection))
    for table in NEW_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        if owners[table]:
            connection.execute(sa.text(f"UPDATE {table} SET tenant_id=:tenant_id WHERE id=:id"),
                [{"id": row_id, "tenant_id": tenant} for row_id, tenant in owners[table].items()])
    op.create_unique_constraint("uq_image_workspace_settings_tenant", "image_workspace_settings", ["tenant_id"])


def downgrade():
    op.drop_constraint("uq_image_workspace_settings_tenant", "image_workspace_settings", type_="unique")
    for table in reversed(NEW_TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
