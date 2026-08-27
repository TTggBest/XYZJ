from datetime import date, datetime, time

from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.services import feishu_sync
from zhiju.services.feishu_sync import (
    business_drama_identifier,
    cell_text,
    normalized_video_id,
    operation_package_completeness,
    operation_package_sync_decision,
    video_id_from_url,
)


def test_feishu_sync_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "/api/v3/feishu-sync/work-orders" in paths
    assert "/api/v3/feishu-sync/operation-packages" in paths
    assert "/api/v3/feishu-sync/channels" in paths


def test_feishu_rich_link_is_normalized_before_video_id_extraction() -> None:
    value = [{"type": "url", "text": "观看剧目", "link": "https://youtu.be/IQ7Cw_wpiqE"}]

    assert cell_text(value) == "https://youtu.be/IQ7Cw_wpiqE"
    assert video_id_from_url(cell_text(value)) == "IQ7Cw_wpiqE"


def test_business_identifier_prefers_video_id_and_falls_back_to_drama_number() -> None:
    assert business_drama_identifier("IQ7Cw_wpiqE", 108) == "IQ7Cw_wpiqE"
    assert business_drama_identifier("", 108) == "108"


def test_pending_placeholder_is_not_treated_as_youtube_video_id() -> None:
    assert normalized_video_id("", "pending_0cf032bf6cc1adf0") == ""
    assert normalized_video_id("https://youtu.be/IQ7Cw_wpiqE", "pending_0cf032bf6cc1adf0") == "IQ7Cw_wpiqE"


def test_channel_and_studio_playlist_ids_are_parsed() -> None:
    assert feishu_sync.youtube_channel_id_from_url(
        "https://www.youtube.com/channel/UCLGDbbXXhR0Vg3ECV4SHlzQ"
    ) == "UCLGDbbXXhR0Vg3ECV4SHlzQ"
    assert feishu_sync.youtube_playlist_id_from_url(
        "https://studio.youtube.com/playlist/PLFAHcxrlFlHI/videos"
    ) == "PLFAHcxrlFlHI"
    assert feishu_sync.youtube_channel_id_from_page(
        '<link rel="canonical" href="https://www.youtube.com/channel/UC1i629yrGlPbI19sBHLVWGA">'
    ) == "UC1i629yrGlPbI19sBHLVWGA"


def test_feishu_rows_keep_their_original_sheet_row_number(monkeypatch) -> None:
    client = object.__new__(feishu_sync.FeishuClient)
    client.app_id = "app"
    client.app_secret = "secret"
    responses = iter([
        {"tenant_access_token": "token"},
        {"data": {"node": {"obj_token": "spreadsheet"}}},
        {"data": {"valueRange": {"values": [
            ["剧名", "档期"],
            ["第一部", "2026082605"],
            [],
            ["第二部", "2026082606"],
        ]}}},
    ])
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: next(responses))

    rows = client.rows("wiki", "sheet", "S")

    assert [row["__source_row_number"] for row in rows] == ["2", "4"]


def test_operation_package_sync_reads_both_community_groups() -> None:
    assert getattr(feishu_sync, "OPERATION_PACKAGE_LAST_COLUMN", None) == "S"


def test_publish_and_first_community_times_are_derived_from_feishu_slot() -> None:
    publish_time = feishu_sync.publish_datetime(date(2026, 8, 26), time(23, 0))

    assert publish_time == datetime(2026, 8, 26, 23, 0)
    assert feishu_sync.community_planned_time(1, publish_time) == datetime(2026, 8, 27, 1, 0)
    assert feishu_sync.community_planned_time(2, publish_time) is None


def test_operation_package_completeness_reports_each_missing_group() -> None:
    complete_row = {
        "标题": "a\nb\nc",
        "标题翻译": "A\nB\nC",
        "封面4：5": "标题1：x\n标题2：y\n标题3：z",
        "封面16：9": "标题1：x\n标题2：y\n标题3：z",
        "播放列表": "主播放列表",
        "说明": "本地语言说明",
        "说明翻译": "中文说明",
        "是否需要社区": "2",
        "社群文案1": "第一条社群文案",
        "社群图描述1": "第一张社群图提示词",
        "社群文案2": "第二条社群文案",
        "社群图描述2": "第二张社群图提示词",
    }

    assert operation_package_completeness(complete_row) == (True, None)

    incomplete_row = {**complete_row, "封面16：9": ""}
    assert operation_package_completeness(incomplete_row) == (
        False,
        "封面16：9需要3组，当前0组",
    )

    incomplete_row = {**complete_row, "说明": "", "社群图描述2": ""}
    assert operation_package_completeness(incomplete_row) == (
        False,
        "说明不能为空；社群图描述2不能为空",
    )


def test_complete_operation_package_is_only_skipped_when_outputs_are_unchanged() -> None:
    assert operation_package_sync_decision(
        existing_source_complete=True,
        incoming_source_complete=True,
        outputs_match=True,
    ) == "skip"
    assert operation_package_sync_decision(
        existing_source_complete=True,
        incoming_source_complete=True,
        outputs_match=False,
    ) == "refresh"
    assert operation_package_sync_decision(
        existing_source_complete=True,
        incoming_source_complete=False,
        outputs_match=True,
    ) == "refresh"


def test_incomplete_package_actions_are_blocked_in_the_ui() -> None:
    app_source = (feishu_sync.APP_ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'button.closest(".source-incomplete")' in app_source
