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
        "youtube_upload_status",
        "copyright_verification_status",
        "subtitle_extraction_status",
        "guishou_upload_status",
        "role_extraction_status",
        "tts_status",
        "production_completion_status",
        "is_production_excluded",
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
        "youtube_upload_status",
        "copyright_verification_status",
        "subtitle_extraction_status",
        "guishou_upload_status",
        "role_extraction_status",
        "tts_status",
        "production_completion_status",
    )
    return SimpleNamespace(
        **dict(zip(fields, values, strict=True)),
        is_production_excluded=False,
    )


def test_progress_calculation_uses_fixed_nine_node_order() -> None:
    from zhiju.services.drama_progress import calculate_progress

    assert calculate_progress(_state(*(["not_started"] * 9))) == (
        0,
        "not_started",
        "cloud_download",
    )
    assert calculate_progress(
        _state(
            "completed",
            "completed",
            "in_progress",
            "not_started",
            "not_started",
            "not_started",
            "not_started",
            "not_started",
            "not_started",
        )
    ) == (22, "in_progress", "youtube_upload")
    assert calculate_progress(_state(*(["completed"] * 9))) == (100, "completed", None)


def test_excluded_drama_has_not_producing_overall_status() -> None:
    from zhiju.services.drama_progress import calculate_progress

    state = _state(*(["completed"] * 9))
    state.is_production_excluded = True

    assert calculate_progress(state) == (100, "not_producing", None)


def test_completing_a_node_backfills_predecessors_and_starts_the_next_node() -> None:
    from zhiju.services.drama_progress import apply_progress_rules

    state = _state(
        "not_started",
        "not_started",
        "not_started",
        "not_started",
        "not_started",
        "completed",
        "not_started",
        "not_started",
        "not_started",
    )

    result = apply_progress_rules(state)

    assert [
        result["cloud_download_status"],
        result["parameter_normalization_status"],
        result["youtube_upload_status"],
        result["copyright_verification_status"],
        result["subtitle_extraction_status"],
        result["guishou_upload_status"],
        result["role_extraction_status"],
    ] == ["completed"] * 6 + ["in_progress"]


def test_production_completion_backfills_all_previous_nodes() -> None:
    from zhiju.services.drama_progress import apply_progress_rules

    result = apply_progress_rules(
        _state(*(["not_started"] * 8), "completed")
    )

    assert list(result.values()) == ["completed"] * 9


def test_progress_validation_rejects_completed_node_after_unfinished_predecessor() -> None:
    from zhiju.services.drama_progress import validate_progress_order

    with pytest.raises(ValueError, match="统一参数"):
        validate_progress_order(
            _state(
                "not_started",
                "in_progress",
                "not_started",
                "not_started",
                "not_started",
                "not_started",
                "not_started",
                "not_started",
                "not_started",
            )
        )


def test_drama_progress_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/drama-production"]
    assert {"get", "put"}.issubset(
        paths["/api/v3/dramas/{drama_id}/production-state"]
    )
    assert "post" in paths[
        "/api/v3/dramas/{drama_id}/production-state/cloud-download/complete"
    ]
    assert "put" in paths[
        "/api/v3/dramas/{drama_id}/production-state/exclusion"
    ]


def test_manual_cloud_download_completion_starts_parameter_normalization() -> None:
    from zhiju.services.drama_progress import complete_cloud_download

    suffix = uuid4().hex[:12]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        drama = models.Drama(
            drama_number=-2,
            drama_code=f"TEST-{suffix}",
            chinese_title=f"测试剧-{suffix}",
            normalized_title=f"测试剧{suffix}",
            source_type="manual",
            status="active",
        )
        session.add(drama)
        session.commit()

        result = complete_cloud_download(session, drama.id)

        assert result["cloud_download_status"] == "completed"
        assert result["parameter_normalization_status"] == "in_progress"
        assert result["overall_status"] == "in_progress"
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_excluding_production_preserves_node_progress_and_can_be_restored() -> None:
    from zhiju.services.drama_progress import (
        complete_cloud_download,
        set_production_exclusion,
    )

    suffix = uuid4().hex[:12]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        drama = models.Drama(
            drama_number=-3,
            drama_code=f"TEST-{suffix}",
            chinese_title=f"测试剧-{suffix}",
            normalized_title=f"测试剧{suffix}",
            source_type="manual",
            status="active",
        )
        session.add(drama)
        session.commit()
        complete_cloud_download(session, drama.id)

        excluded = set_production_exclusion(session, drama.id, excluded=True)
        restored = set_production_exclusion(session, drama.id, excluded=False)

        assert excluded["overall_status"] == "not_producing"
        assert restored["overall_status"] == "in_progress"
        assert restored["cloud_download_status"] == "completed"
        assert restored["parameter_normalization_status"] == "in_progress"
    finally:
        session.close()
        transaction.rollback()
        connection.close()


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
            drama_number=-1,
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
    for label in (
        "网盘下载",
        "统一参数",
        "上传 YouTube",
        "版权验证",
        "字幕提取",
        "鬼手上传",
        "角色提取",
        "TTS",
        "制作完成",
        "剧集数",
        "合集总时长",
        "不制作",
    ):
        assert label in source
    assert 'data-action="complete-cloud-download"' in source
    assert 'data-action="exclude-drama-production"' in source
    assert 'window.confirm(' in source
    assert '["S", "A", "B", "C"]' in source


def test_frontend_compacts_drama_progress_table_for_desktop_width() -> None:
    app_source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    style_source = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")

    assert "function compactDramaBatch(value)" in app_source
    assert "function dramaProgressUpdatedAt(value)" in app_source
    assert 'class="drama-progress-title-cell"' in app_source
    assert 'class="drama-progress-spec-cell"' in app_source
    assert 'class="drama-progress-updated-cell"' in app_source
    assert '"规格", "整体进度", "最后更新"' in app_source
    assert 'rows, 1320, "drama-progress-table"' in app_source
    assert ".drama-progress-table .data-table th," in style_source
    assert ".drama-progress-title-cell" in style_source
    assert ".drama-progress-updated-cell" in style_source


def test_frontend_uses_single_vertical_scroll_for_drama_progress() -> None:
    app_source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    style_source = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")

    assert 'root.classList.toggle("is-workspace-scroll-locked", view === "dramaProgress")' in app_source
    assert 'el("appShell").classList.toggle("is-workspace-scroll-locked", view === "dramaProgress")' in app_source
    assert 'class="page-stack drama-progress-page"' in app_source
    assert ".view-root.is-workspace-scroll-locked" in style_source
    assert ".app-shell.is-workspace-scroll-locked .main-area" in style_source
    assert ".drama-progress-page > .section" in style_source
    assert "overscroll-behavior: contain" in style_source
    assert "max-height: none" in style_source
