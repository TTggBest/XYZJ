from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint

from zhiju.app import app
from zhiju.models import Drama, FeishuSyncRun
from zhiju.services import feishu_sync


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


def test_drama_feishu_sync_route_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "post" in paths["/api/v3/feishu-sync/dramas"]


def test_drama_feishu_value_mapping_uses_beijing_day_end() -> None:
    parse_expiry = getattr(feishu_sync, "parse_drama_expiry", None)
    map_status = getattr(feishu_sync, "map_drama_status", None)

    assert callable(parse_expiry)
    assert callable(map_status)
    assert parse_expiry("2026-08-31") == datetime(2026, 8, 31, 23, 59, 59)
    assert parse_expiry("") is None
    assert map_status("制作") == "active"
    assert map_status("") == "active"
    assert map_status("已删") == "archived"


def test_feishu_client_resolves_sheet_by_exact_title(monkeypatch) -> None:
    resolver = getattr(feishu_sync.FeishuClient, "sheet_id_by_title", None)
    assert callable(resolver)
    client = feishu_sync.FeishuClient("app", "secret")

    monkeypatch.setattr(
        client,
        "_spreadsheet_access",
        lambda wiki_token: ("token", "spreadsheet"),
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, token="", payload=None: {
            "data": {
                "sheets": [
                    {"sheet_id": "OHTcqg", "title": "语言"},
                    {"sheet_id": "b8b567", "title": "剧库表"},
                ]
            }
        },
    )

    assert client.sheet_id_by_title("wiki", "剧库表") == "b8b567"


def test_drama_library_frontend_uses_paginated_workspace() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'api(`/dramas/library${query(' in source
    assert 'data-action="sync-feishu-dramas"' in source
    assert 'data-action="bulk-add-dramas"' in source
    assert 'data-action="drama-library-page"' in source
    assert 'data-drama-tab="languages"' in source
    assert 'data-drama-tab="channels"' in source


def test_drama_bulk_csv_route_and_parser_support_quoted_content() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    parser = getattr(__import__("zhiju.services.drama_library", fromlist=["parse_drama_csv"]), "parse_drama_csv", None)

    assert "post" in paths["/api/v3/dramas/bulk-csv"]
    assert callable(parser)
    payload = parser(
        '作品名称,内容概述,批次,状态\n'
        '测试剧,"第一行,仍是同一字段\n第二行",B-01,制作\n'
    )
    assert payload.rows[0].chinese_title == "测试剧"
    assert payload.rows[0].content_summary == "第一行,仍是同一字段\n第二行"
    assert payload.rows[0].batch_name == "B-01"
