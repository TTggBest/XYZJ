"""Scope integration credentials, sync keys, and demo entities by tenant."""

from alembic import op
import sqlalchemy as sa


revision = "b7d0e3f8a276"
down_revision = "a6c9d2e7f165"
branch_labels = None
depends_on = None

ROOT_COLUMNS = {
    "integration_accounts": ("tenant_id", "integration_id", "account_key"),
    "production_batches": ("tenant_id", "batch_number"),
    "operation_tasks": ("tenant_id", "idempotency_key"),
    "demo_data_batches": ("tenant_id", "batch_code"),
    "feishu_sync_runs": ("tenant_id",),
    "dramas": ("tenant_id", "normalized_title"),
}
CHILDREN = {
    "integration_credentials": {
        "parent_table": "integration_accounts",
        "parent_column": "integration_account_id",
        "business_columns": ("credential_type",),
    },
    "demo_data_entities": {
        "parent_table": "demo_data_batches",
        "parent_column": "batch_id",
        "business_columns": ("entity_type", "entity_id"),
    },
}


def load_rows(connection):
    rows = {
        table: list(connection.execute(sa.text(
            f"SELECT id, {', '.join(columns)} FROM {table}"
        )).mappings())
        for table, columns in ROOT_COLUMNS.items()
    }
    for table, spec in CHILDREN.items():
        columns = (spec["parent_column"], *spec["business_columns"])
        rows[table] = list(connection.execute(sa.text(
            f"SELECT id, {', '.join(columns)} FROM {table}"
        )).mappings())
    return rows


def _reject_duplicates(table, rows, columns):
    seen = set()
    for row in rows:
        key = tuple(row[column] for column in columns)
        if key in seen:
            raise RuntimeError(f"{table}:{row['id']} duplicate tenant business key")
        seen.add(key)


def validate_owners(rows):
    owners = {}
    for table, columns in ROOT_COLUMNS.items():
        owners[table] = {}
        for row in rows[table]:
            if not row["tenant_id"]:
                raise RuntimeError(f"{table}:{row['id']} missing tenant")
            owners[table][row["id"]] = row["tenant_id"]
        if len(columns) > 1:
            _reject_duplicates(table, rows[table], columns)

    for table, spec in CHILDREN.items():
        owners[table] = {}
        parent_column = spec["parent_column"]
        parent_owners = owners[spec["parent_table"]]
        derived_rows = []
        for row in rows[table]:
            tenant_id = parent_owners.get(row[parent_column])
            if not tenant_id:
                raise RuntimeError(f"{table}:{row['id']} {parent_column} has no derivable tenant")
            owners[table][row["id"]] = tenant_id
            derived_rows.append({**row, "tenant_id": tenant_id})
        _reject_duplicates(
            table, derived_rows, ("tenant_id", parent_column, *spec["business_columns"]),
        )
    return owners


UNIQUE_CHANGES = (
    ("integration_accounts", "uq_integration_accounts_key", "uq_integration_accounts_tenant_key",
     ("tenant_id", "integration_id", "account_key")),
    ("integration_credentials", "uq_integration_credentials_type", "uq_integration_credentials_tenant_type",
     ("tenant_id", "integration_account_id", "credential_type")),
    ("production_batches", "uq_production_batches_batch_number", "uq_production_batches_tenant_number",
     ("tenant_id", "batch_number")),
    ("operation_tasks", "uq_operation_tasks_idempotency_key", "uq_operation_tasks_tenant_idempotency",
     ("tenant_id", "idempotency_key")),
    ("demo_data_batches", "uq_demo_data_batches_batch_code", "uq_demo_data_batches_tenant_code",
     ("tenant_id", "batch_code")),
    ("demo_data_entities", "uq_demo_data_entities_entity", "uq_demo_data_entities_tenant_entity",
     ("tenant_id", "entity_type", "entity_id")),
    ("dramas", "uq_dramas_normalized_title", "uq_dramas_tenant_normalized_title",
     ("tenant_id", "normalized_title")),
)


def upgrade():
    connection = op.get_bind()
    # MySQL ALTER commits implicitly: validate all parents and duplicate keys first.
    owners = validate_owners(load_rows(connection))
    for table in CHILDREN:
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        if owners[table]:
            connection.execute(sa.text(
                f"UPDATE {table} SET tenant_id=:tenant_id WHERE id=:id"
            ), [
                {"id": row_id, "tenant_id": tenant_id}
                for row_id, tenant_id in owners[table].items()
            ])
    for table, old_name, new_name, columns in UNIQUE_CHANGES:
        op.drop_constraint(old_name, table, type_="unique")
        op.create_unique_constraint(new_name, table, list(columns))


def downgrade():
    for table, old_name, new_name, columns in reversed(UNIQUE_CHANGES):
        op.drop_constraint(new_name, table, type_="unique")
        op.create_unique_constraint(old_name, table, list(columns[1:]))
    for table in reversed(CHILDREN):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
