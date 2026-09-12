import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, create_engine

from scripts.audit_tenant_isolation import (
    _orphan_count,
    read_development_database_url,
    require_expected_database,
    validate_preflight,
)


def test_preflight_rejects_multiple_heads() -> None:
    report = {
        "alembic_heads": ["a", "b"],
        "table_counts": {},
        "parent_chain_orphans": {},
        "known_unique_key_duplicates": {},
        "rows_without_derivable_tenant": {},
    }

    assert validate_preflight(report) == ["multiple_alembic_heads"]


def test_preflight_accepts_one_head_without_data_findings() -> None:
    report = {
        "alembic_heads": ["a"],
        "table_counts": {},
        "parent_chain_orphans": {},
        "known_unique_key_duplicates": {},
        "rows_without_derivable_tenant": {},
    }

    assert validate_preflight(report) == []


def test_preflight_refuses_any_database_other_than_zhiju_dev() -> None:
    with pytest.raises(ValueError, match="zhiju_dev"):
        require_expected_database("mysql+pymysql://user:pass@localhost/zhiju_prod", "zhiju_dev")


def test_preflight_refuses_a_non_development_config_before_connecting(tmp_path) -> None:
    config_path = tmp_path / ".env"
    config_path.write_text(
        "ZHJ_DATABASE_URL=mysql+pymysql://user:pass@localhost/zhiju_prod\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="zhiju_dev"):
        read_development_database_url(config_path)


def test_preflight_counts_self_referential_foreign_keys_without_alias_collision() -> None:
    metadata = MetaData()
    users = Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("created_by_user_id", Integer, ForeignKey("users.id")),
    )
    engine = create_engine("sqlite://")
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(users.insert(), [{"id": 1}, {"id": 2, "created_by_user_id": 1}])

        constraint = next(iter(users.foreign_key_constraints))
        assert _orphan_count(engine, users, constraint) == 0
    finally:
        engine.dispose()
