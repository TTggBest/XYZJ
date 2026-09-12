"""Scope drama and schedule children after validating their strong parents.

Revision ID: d3f6a9b4c832
Revises: c2e5f8a3b721
"""
from alembic import op
import sqlalchemy as sa


revision = "d3f6a9b4c832"
down_revision = "c2e5f8a3b721"
branch_labels = None
depends_on = None

PARENTS = {
    "drama_aliases": {"drama_id": "dramas"},
    "drama_core_terms": {"drama_id": "dramas"},
    "drama_translations": {"drama_id": "dramas"},
    "drama_production_states": {"drama_id": "dramas"},
    "schedule_candidates": {"schedule_id": "channel_schedule_entries", "drama_id": "dramas"},
    "schedule_change_history": {"schedule_id": "channel_schedule_entries", "old_drama_id": "dramas", "new_drama_id": "dramas"},
}
OPTIONAL_PARENTS = {("schedule_change_history", "old_drama_id"),
                    ("schedule_change_history", "new_drama_id")}


def _validated_owners(connection):
    owners = {}
    for name in ("channels", "dramas"):
        owners[name] = dict(connection.execute(sa.text(f"SELECT id, tenant_id FROM {name}")).all())
    owners["channel_schedule_entries"] = {}
    for row in connection.execute(sa.text(
        "SELECT id, tenant_id, channel_id, drama_id FROM channel_schedule_entries"
    )).mappings():
        tenant_id = row["tenant_id"]
        if not tenant_id or any(owners[parent].get(row[column]) != tenant_id for column, parent in (
            ("channel_id", "channels"), ("drama_id", "dramas"),
        )):
            raise RuntimeError(f"channel_schedule_entries:{row['id']} parent tenant mismatch or missing")
        owners["channel_schedule_entries"][row["id"]] = tenant_id
    # Finish all validation before MySQL's non-transactional ALTER TABLE begins.
    for name, parents in PARENTS.items():
        owners[name] = {}
        for row in connection.execute(sa.text(f"SELECT id, {', '.join(parents)} FROM {name}")).mappings():
            tenant_ids = set()
            for column, parent in parents.items():
                if row[column] is None and (name, column) in OPTIONAL_PARENTS:
                    continue
                tenant_id = owners[parent].get(row[column])
                if not tenant_id:
                    raise RuntimeError(f"{name}:{row['id']} {column} has no derivable tenant")
                tenant_ids.add(tenant_id)
            if len(tenant_ids) != 1:
                raise RuntimeError(f"{name}:{row['id']} parent tenant mismatch")
            owners[name][row["id"]] = tenant_ids.pop()
    return owners


def upgrade():
    connection = op.get_bind()
    owners = _validated_owners(connection)
    for name in PARENTS:
        op.add_column(name, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])
        if owners[name]:
            connection.execute(sa.text(f"UPDATE {name} SET tenant_id = :tenant_id WHERE id = :id"),
                [{"id": row_id, "tenant_id": tenant_id} for row_id, tenant_id in owners[name].items()])


def downgrade():
    for name in reversed(PARENTS):
        op.drop_index(f"ix_{name}_tenant_id", table_name=name)
        op.drop_column(name, "tenant_id")
