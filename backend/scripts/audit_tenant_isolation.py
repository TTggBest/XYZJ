from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import and_, create_engine, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.schema import ForeignKeyConstraint, Table, UniqueConstraint

from zhiju.config import APP_ROOT
from zhiju.models import Base


EXPECTED_DATABASE = "zhiju_dev"
GLOBAL_TABLES = frozenset(
    {
        "app_icon_settings",
        "app_users",
        "auth_events",
        "auth_sessions",
        "device_user_bindings",
        "devices",
        "integrations",
        "languages",
        "permissions",
        "publish_cadence_template_slots",
        "role_permissions",
        "runtime_package_builds",
        "schema_comments",
        "skills",
        "skill_versions",
        "tenant_memberships",
        "tenants",
    }
)


def require_expected_database(database_url: str, expected_database: str) -> None:
    if expected_database != EXPECTED_DATABASE:
        raise ValueError(f"预检只允许 --expect-database {EXPECTED_DATABASE}")
    if make_url(database_url).database != EXPECTED_DATABASE:
        raise ValueError(f"预检只允许数据库 {EXPECTED_DATABASE}")


def read_development_database_url(config_path: Path = APP_ROOT / ".env") -> str:
    if not config_path.is_file():
        raise FileNotFoundError(f"未找到代码机开发配置：{config_path}")
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("ZHJ_DATABASE_URL="):
            database_url = line.split("=", 1)[1].strip()
            require_expected_database(database_url, EXPECTED_DATABASE)
            return database_url
    raise ValueError(f"代码机开发配置未提供 ZHJ_DATABASE_URL：{config_path}")


def validate_preflight(report: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if len(report["alembic_heads"]) != 1:
        findings.append("multiple_alembic_heads")
    for key in (
        "parent_chain_orphans",
        "known_unique_key_duplicates",
        "rows_without_derivable_tenant",
    ):
        if any(report[key].values()):
            findings.append(key)
    return findings


def _alembic_heads() -> list[str]:
    config = Config(str(APP_ROOT / "alembic.ini"))
    return sorted(ScriptDirectory.from_config(config).get_heads())


def _table_count(engine: Engine, table: Table) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def _orphan_count(engine: Engine, table: Table, constraint: ForeignKeyConstraint) -> int:
    foreign_keys = tuple(constraint.elements)
    local_columns = tuple(element.parent for element in foreign_keys)
    remote_columns = tuple(element.column for element in foreign_keys)
    parent_table = remote_columns[0].table
    parent_alias = parent_table.alias()
    join_condition = and_(
        *(
            local_column == parent_alias.c[remote_column.key]
            for local_column, remote_column in zip(local_columns, remote_columns)
        )
    )
    present_local_value = and_(*(column.is_not(None) for column in local_columns))
    missing_parent = parent_alias.c[remote_columns[0].key].is_(None)
    statement = (
        select(func.count())
        .select_from(table.outerjoin(parent_alias, join_condition))
        .where(present_local_value, missing_parent)
    )
    with engine.connect() as connection:
        return int(connection.scalar(statement) or 0)


def _unique_column_groups(table: Table) -> Iterable[tuple[str, tuple[Any, ...]]]:
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            columns = tuple(constraint.columns)
            yield constraint.name or f"uq_{table.name}_{'_'.join(column.name for column in columns)}", columns
    for column in table.columns:
        if column.unique:
            yield f"uq_{table.name}_{column.name}", (column,)


def _duplicate_group_count(engine: Engine, table: Table, columns: tuple[Any, ...]) -> int:
    non_null_values = and_(*(column.is_not(None) for column in columns))
    duplicate_groups = (
        select(*columns)
        .select_from(table)
        .where(non_null_values)
        .group_by(*columns)
        .having(func.count() > 1)
        .subquery()
    )
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(duplicate_groups)) or 0)


def build_preflight_report(engine: Engine) -> dict[str, Any]:
    tables = tuple(sorted(Base.metadata.tables.values(), key=lambda table: table.name))
    table_counts = {table.name: _table_count(engine, table) for table in tables}

    parent_chain_orphans: dict[str, int] = {}
    known_unique_key_duplicates: dict[str, int] = {}
    rows_without_derivable_tenant: dict[str, int] = {}
    for table in tables:
        for constraint in table.foreign_key_constraints:
            count = _orphan_count(engine, table, constraint)
            if count:
                key = constraint.name or f"fk_{table.name}_{'_'.join(column.name for column in constraint.columns)}"
                parent_chain_orphans[key] = count
        for key, columns in _unique_column_groups(table):
            count = _duplicate_group_count(engine, table, columns)
            if count:
                known_unique_key_duplicates[key] = count
        if table.name not in GLOBAL_TABLES and "tenant_id" not in table.c and table_counts[table.name]:
            rows_without_derivable_tenant[table.name] = table_counts[table.name]

    report = {
        "alembic_heads": _alembic_heads(),
        "table_counts": table_counts,
        "parent_chain_orphans": parent_chain_orphans,
        "known_unique_key_duplicates": known_unique_key_duplicates,
        "rows_without_derivable_tenant": rows_without_derivable_tenant,
    }
    report["findings"] = validate_preflight(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读租户隔离迁移预检")
    parser.add_argument("--expect-database", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.expect_database != EXPECTED_DATABASE:
        raise ValueError(f"预检只允许 --expect-database {EXPECTED_DATABASE}")
    database_url = read_development_database_url()
    require_expected_database(database_url, args.expect_database)
    engine = create_engine(database_url)
    try:
        print(json.dumps(build_preflight_report(engine), ensure_ascii=False, sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
