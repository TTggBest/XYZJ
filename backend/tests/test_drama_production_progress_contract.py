from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Session

from zhiju import models
from zhiju.app import app
from zhiju.database import database_router


ROOT = Path(__file__).resolve().parents[2]


def _check_sql(model: type) -> str:
    return " ".join(
        str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_drama_production_state_is_unique_per_drama_and_has_fixed_nodes() -> None:
    production_state = getattr(models, "DramaProductionState", None)

    assert production_state is not None
    columns = production_state.__table__.columns
    assert {
        "cloud_download_status",
        "parameter_normalization_status",
        "subtitle_extraction_status",
        "guishou_upload_status",
        "role_extraction_status",
        "production_completion_status",
        "episode_count",
        "total_duration_seconds",
        "source_type",
        "source_external_id",
        "source_updated_at",
        "source_synced_at",
        "last_error",
    }.issubset(columns.keys())
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(constraint.columns.keys()) == ("drama_id",)
        for constraint in production_state.__table__.constraints
    )
    checks = _check_sql(production_state)
    for value in ("not_started", "in_progress", "completed", "failed"):
        assert value in checks
    assert "source_type IN ('manual','zhihe')" in checks


def test_language_and_translation_models_track_priority_and_source() -> None:
    assert "priority_tier" in models.Language.__table__.columns
    assert "source_type" in models.DramaTranslation.__table__.columns
    assert "source_synced_at" in models.DramaTranslation.__table__.columns
    assert "priority_tier IN ('S','A','B','C')" in _check_sql(models.Language)
    assert "source_type IN ('manual','feishu')" in _check_sql(models.DramaTranslation)


def test_drama_progress_migration_follows_phase_one_head() -> None:
    migrations = list(
        (ROOT / "backend" / "alembic" / "versions").glob(
            "*_add_drama_production_progress.py"
        )
    )

    assert len(migrations) == 1
    source = migrations[0].read_text(encoding="utf-8")
    assert 'down_revision = "5db7a3c821e4"' in source
    assert "drama_production_states" in source
    assert "priority_tier" in source
    assert "drama_languages" in source


def _state(*values: str) -> SimpleNamespace:
    fields = (
        "cloud_download_status",
        "parameter_normalization_status",
        "subtitle_extraction_status",
        "guishou_upload_status",
        "role_extraction_status",
        "production_completion_status",
    )
    return SimpleNamespace(**dict(zip(fields, values, strict=True)))


def test_progress_calculation_uses_fixed_six_node_order() -> None:
    from zhiju.services.drama_progress import calculate_progress

    assert calculate_progress(_state(*(["not_started"] * 6))) == (
        0,
        "not_started",
        "cloud_download",
    )
    assert calculate_progress(
        _state("completed", "completed", "in_progress", "not_started", "not_started", "not_started")
    ) == (33, "in_progress", "subtitle_extraction")
    assert calculate_progress(_state(*(["completed"] * 6))) == (100, "completed", None)


def test_progress_validation_rejects_completed_node_after_unfinished_predecessor() -> None:
    from zhiju.services.drama_progress import validate_progress_order

    with pytest.raises(ValueError, match="统一参数"):
        validate_progress_order(
            _state("not_started", "completed", "not_started", "not_started", "not_started", "not_started")
        )


def test_drama_progress_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/drama-production"]
    assert {"get", "put"}.issubset(
        paths["/api/v3/dramas/{drama_id}/production-state"]
    )


def test_manual_drama_language_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert {"put", "delete"}.issubset(
        paths["/api/v3/dramas/{drama_id}/languages/{language_id}"]
    )


def test_feishu_language_coverage_cannot_be_deleted_manually() -> None:
    from zhiju.api.drama_library import remove_drama_language

    suffix = uuid4().hex[:12]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        drama = models.Drama(
            drama_code=f"TEST-{suffix}",
            chinese_title=f"测试剧-{suffix}",
            normalized_title=f"测试剧{suffix}",
            source_type="manual",
            status="active",
        )
        language = models.Language(
            code=f"x-{suffix}",
            name_zh=f"测试语言-{suffix}",
            priority_tier="C",
            status="active",
        )
        session.add_all([drama, language])
        session.flush()
        coverage = models.DramaTranslation(
            drama_id=drama.id,
            language_id=language.id,
            translation_status="ready",
            asset_status="ready",
            source_type="feishu",
        )
        session.add(coverage)
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            remove_drama_language(drama.id, language.id, session)

        assert exc_info.value.status_code == 409
        assert "飞书" in str(exc_info.value.detail)
        assert session.get(models.DramaTranslation, coverage.id) is not None
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_frontend_exposes_progress_workspace_and_language_groups() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'dramaProgress: ["剧库", "制剧进度"]' in source
    assert 'data-action="go-drama-progress"' in source
    assert 'data-action="edit-drama-progress"' in source
    assert 'data-action="sync-feishu-drama-languages"' in source
    assert 'data-action="toggle-drama-language"' in source
    for label in ("网盘下载", "统一参数", "字幕提取", "鬼手上传", "角色提取", "制作完成"):
        assert label in source
    assert '["S", "A", "B", "C"]' in source
