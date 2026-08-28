from pathlib import Path

from sqlalchemy import CheckConstraint

from zhiju import models
from zhiju.schemas.operations import ScheduleRead


ROOT = Path(__file__).resolve().parents[2]


def _check_sql(model: type) -> str:
    return " ".join(
        str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_channel_schedule_tracks_feishu_provenance_and_video_execution_state() -> None:
    columns = models.ChannelScheduleEntry.__table__.columns

    assert {
        "source_type",
        "source_sheet_id",
        "source_row_number",
        "source_synced_at",
        "source_video_id",
        "source_video_url",
        "is_uploaded",
        "is_published",
        "is_task_written",
    }.issubset(columns.keys())
    assert "source_type IN ('manual','feishu','system')" in _check_sql(
        models.ChannelScheduleEntry
    )
    assert columns["source_type"].server_default.arg == "manual"
    assert columns["is_uploaded"].server_default.arg == "0"
    assert columns["is_published"].server_default.arg == "0"
    assert columns["is_task_written"].server_default.arg == "0"


def test_schedule_read_exposes_feishu_provenance_fields() -> None:
    assert {
        "source_type",
        "source_sheet_id",
        "source_row_number",
        "source_synced_at",
        "source_video_id",
        "source_video_url",
        "is_uploaded",
        "is_published",
        "is_task_written",
    }.issubset(ScheduleRead.model_fields)


def test_feishu_channel_schedule_migration_follows_current_head() -> None:
    migrations = list(
        (ROOT / "backend" / "alembic" / "versions").glob(
            "*_add_feishu_channel_schedule_fields.py"
        )
    )

    assert len(migrations) == 1
    source = migrations[0].read_text(encoding="utf-8")
    assert 'down_revision = "c3f8a1b7d902"' in source
    for column_name in (
        "source_type",
        "source_sheet_id",
        "source_row_number",
        "source_synced_at",
        "source_video_id",
        "source_video_url",
        "is_uploaded",
        "is_published",
        "is_task_written",
    ):
        assert column_name in source
