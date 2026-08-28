from pathlib import Path
from datetime import datetime, time
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Session

from zhiju import models
from zhiju.database import database_router
from zhiju.config import Settings
from zhiju.schemas.operations import ScheduleRead
from zhiju.services import feishu_sync
from zhiju.services.feishu_sync import FeishuSyncError


ROOT = Path(__file__).resolve().parents[2]


def test_channel_schedule_workbook_has_dedicated_read_configuration() -> None:
    field = Settings.model_fields.get("feishu_channel_schedule_wiki_token")

    assert field is not None
    assert field.default == "ErwWwX8TVionsikFwQMcEpCenih"
    assert Settings.model_fields["feishu_channel_schedule_directory_sheet_id"].default == "2FrKIE"


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


def test_confirmed_malformed_schedule_date_is_corrected_narrowly() -> None:
    parsed, corrected = feishu_sync.parse_feishu_schedule_datetime(
        "2026-08-010 12:00",
        sheet_title="测试频道",
        row_number=8,
    )

    assert parsed == datetime(2026, 8, 10, 12, 0)
    assert corrected is True

    with pytest.raises(FeishuSyncError, match="测试频道.*第 9 行.*档期时间"):
        feishu_sync.parse_feishu_schedule_datetime(
            "2026-08-011 12:00",
            sheet_title="测试频道",
            row_number=9,
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", False), ("0", False), ("1", True)],
)
def test_schedule_flags_only_accept_zero_one_or_blank(raw: str, expected: bool) -> None:
    assert feishu_sync.parse_feishu_schedule_flag(
        raw,
        field_name="是否上传",
        sheet_title="测试频道",
        row_number=2,
    ) is expected


def test_schedule_flag_rejects_unknown_value() -> None:
    with pytest.raises(FeishuSyncError, match="是否上传"):
        feishu_sync.parse_feishu_schedule_flag(
            "是",
            field_name="是否上传",
            sheet_title="测试频道",
            row_number=2,
        )


def test_feishu_client_lists_workbook_sheets_with_one_access_session(monkeypatch) -> None:
    client = object.__new__(feishu_sync.FeishuClient)
    client.app_id = "app"
    client.app_secret = "secret"
    client.base_url = "https://open.feishu.cn/open-apis"
    responses = iter([
        {"tenant_access_token": "tenant-token"},
        {"data": {"node": {"obj_token": "spreadsheet-token"}}},
        {"data": {"sheets": [
            {"sheet_id": "2FrKIE", "title": "频道目录"},
            {"sheet_id": "sheet-a", "title": "频道昵称"},
        ]}},
    ])
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: next(responses))

    token, spreadsheet_token, sheets = client.workbook_sheets("wiki-token")

    assert token == "tenant-token"
    assert spreadsheet_token == "spreadsheet-token"
    assert [(sheet["sheet_id"], sheet["title"]) for sheet in sheets] == [
        ("2FrKIE", "频道目录"),
        ("sheet-a", "频道昵称"),
    ]


def test_prepare_channel_schedule_rows_resolves_directory_channel_alias_drama_and_slot() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = models.Channel(
            youtube_channel_id=f"UC-FEISHU-{suffix}",
            original_name=f"频道原名-{suffix}",
            operational_name=f"频道昵称-{suffix}",
            timezone="Asia/Jakarta",
            daily_publish_count=1,
            status="active",
        )
        drama = models.Drama(
            drama_number=-int(suffix[:8], 16),
            drama_code=f"FSC-{suffix}",
            chinese_title=f"正式剧名-{suffix}",
            normalized_title=f"正式剧名-{suffix}".casefold(),
            source_type="manual",
            status="active",
        )
        session.add_all([channel, drama])
        session.flush()
        slot = models.ChannelPublishSlot(
            channel_id=channel.id,
            slot_type="main",
            slot_number=1,
            local_time=time(19, 0),
            timezone="Asia/Jakarta",
            status="active",
        )
        session.add_all([
            slot,
            models.DramaAlias(
                drama_id=drama.id,
                alias=f"排期别名-{suffix}",
                normalized_alias=f"排期别名-{suffix}".casefold(),
                source="manual",
            ),
        ])
        session.commit()

        prepared, corrected_count = feishu_sync.prepare_channel_schedule_rows(
            session,
            directory_rows=[{
                "频道名": channel.original_name,
                "频道昵称": channel.operational_name,
                "链接": "https://example.feishu.cn/wiki/token?sheet=sheet-a",
                "__source_row_number": "2",
            }],
            sheet_rows=[(
                "sheet-a",
                channel.operational_name,
                [{
                    "剧名": f"排期别名-{suffix}",
                    "videoId": "https://youtu.be/IQ7Cw_wpiqE",
                    "链接": "https://youtu.be/IQ7Cw_wpiqE",
                    "档期": "主档",
                    "档期时间": "2026-08-29 20:00",
                    "是否上传": "1",
                    "是否上线": "0",
                    "是否写入任务": "1",
                    "__source_row_number": "2",
                }],
            )],
        )

        assert corrected_count == 0
        assert len(prepared) == 1
        item = prepared[0]
        assert item["channel_id"] == channel.id
        assert item["drama_id"] == drama.id
        assert item["publish_slot_id"] == slot.id
        assert item["publish_date"].isoformat() == "2026-08-29"
        assert item["planned_local_time"] == datetime(2026, 8, 29, 19, 0)
        assert item["planned_beijing_time"] == datetime(2026, 8, 29, 20, 0)
        assert item["source_video_id"] == "IQ7Cw_wpiqE"
        assert item["is_uploaded"] is True
        assert item["is_published"] is False
        assert item["is_task_written"] is True
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_prepare_channel_schedule_rows_does_not_create_unknown_business_entities() -> None:
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        with pytest.raises(FeishuSyncError, match="频道目录.*未匹配智矩频道"):
            feishu_sync.prepare_channel_schedule_rows(
                session,
                directory_rows=[{
                    "频道名": "不存在的频道",
                    "频道昵称": "不存在的频道昵称",
                    "链接": "https://example.feishu.cn/wiki/token?sheet=missing",
                    "__source_row_number": "2",
                }],
                sheet_rows=[("missing", "不存在的频道昵称", [])],
            )
    finally:
        session.close()
        transaction.rollback()
        connection.close()
