import pytest
from sqlalchemy import create_engine

from zhiju.config import Settings
from zhiju.database import TenantSession
from zhiju.models import Base, Channel, Drama
from zhiju.services import feishu_sync


@pytest.fixture
def schedule_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-test"}) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("configured", (True, False))
def test_schedule_sync_uses_current_tenant_source_and_only_directory_channels(schedule_session, monkeypatch, configured):
    session = schedule_session
    settings = Settings(database_url="sqlite://", feishu_channel_schedule_sources={
        "tenant-test" if configured else "other-tenant": {
            "wiki_token": "NDyCw5M9iiqTLlkcGGHcbWr1n2c", "directory_sheet_id": "43e1df",
        },
    })
    monkeypatch.setattr(feishu_sync, "get_settings", lambda: settings)
    expected_wiki = "NDyCw5M9iiqTLlkcGGHcbWr1n2c" if configured else "ErwWwX8TVionsikFwQMcEpCenih"
    expected_directory = "43e1df" if configured else "2FrKIE"
    session.add(Channel(youtube_channel_id="UC-test", original_name="测试频道",
                        timezone="Asia/Shanghai", daily_publish_count=1, status="active"))
    session.commit()
    session.add(Drama(drama_number=1, drama_code="TEST-1", chinese_title="测试剧1",
                      normalized_title="测试剧1", source_type="manual", status="active"))
    session.commit()
    reads = []

    class Client:
        def workbook_sheets(self, wiki):
            assert wiki == expected_wiki
            return "test-token", "test-workbook", [
                {"sheet_id": expected_directory, "title": "频道目录"},
                {"sheet_id": "hK3ISh", "title": "测试频道"},
                {"sheet_id": "YEj3r2", "title": "制作优先级"},
            ]

        def rows_from_workbook(self, token, workbook, sheet, last_column):
            reads.append(sheet)
            if sheet == expected_directory:
                return [{"频道名": "测试频道", "链接": "hK3ISh", "__source_row_number": "2"}]
            assert sheet == "hK3ISh", "制作优先级不能作为频道排期读取"
            return [{"剧名": "测试剧1", "档期": "主档", "档期时间": "2026-10-26 00:00:00", "__source_row_number": "2"}]

    monkeypatch.setattr(feishu_sync, "_client", Client)
    result = feishu_sync.sync_channel_schedules(session)
    assert reads == [expected_directory, "hK3ISh"]
    assert result["sheets_read"] == 1
    assert result["rows_read"] == 1
    assert result["rows_inserted"] == 1


def test_schedule_source_environment_accepts_tenant_mapping(monkeypatch):
    monkeypatch.setenv("ZHJ_FEISHU_CHANNEL_SCHEDULE_SOURCES", '{"tenant-test":{"wiki_token":"new-wiki","directory_sheet_id":"new-directory"}}')
    settings = Settings(database_url="sqlite://")
    assert settings.feishu_channel_schedule_sources["tenant-test"].wiki_token == "new-wiki"
    assert settings.feishu_channel_schedule_sources["tenant-test"].directory_sheet_id == "new-directory"
