from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint

from zhiju.app import app
from zhiju.models import Drama, FeishuSyncRun


ROOT = Path(__file__).resolve().parents[2]


def test_drama_model_tracks_feishu_source_metadata() -> None:
    columns = Drama.__table__.columns

    assert columns["batch_name"].nullable is True
    assert columns["source_type"].nullable is False
    assert columns["source_sheet_id"].nullable is True
    assert columns["source_row_number"].nullable is True
    assert columns["source_synced_at"].nullable is True
    assert "manual" in str(columns["source_type"].server_default.arg)


def test_drama_source_and_feishu_sync_constraints_cover_new_values() -> None:
    drama_checks = " ".join(
        str(constraint.sqltext)
        for constraint in Drama.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    )
    sync_checks = " ".join(
        str(constraint.sqltext)
        for constraint in FeishuSyncRun.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    )

    assert "source_type IN ('manual','feishu')" in drama_checks
    assert "'dramas'" in sync_checks


def test_drama_library_migration_follows_current_head() -> None:
    migrations = list(
        (ROOT / "backend" / "alembic" / "versions").glob(
            "*_add_drama_library_source_fields.py"
        )
    )

    assert len(migrations) == 1
    source = migrations[0].read_text(encoding="utf-8")
    assert 'down_revision = "b14c7e2a90d3"' in source
    assert "batch_name" in source
    assert "source_synced_at" in source
    assert "'dramas'" in source


def test_drama_library_management_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/dramas/library"]
    assert {"get", "patch"}.issubset(paths["/api/v3/dramas/{drama_id}"])
    assert "post" in paths["/api/v3/dramas/bulk"]


def test_drama_library_summary_casts_boolean_counts_to_integers() -> None:
    source = (
        ROOT / "backend" / "zhiju" / "services" / "drama_library.py"
    ).read_text(encoding="utf-8")

    assert 'cast(Drama.status == "active", Integer)' in source
    assert 'cast(Drama.status == "archived", Integer)' in source
