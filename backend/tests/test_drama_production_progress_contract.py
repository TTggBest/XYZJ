from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

from zhiju import models


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
