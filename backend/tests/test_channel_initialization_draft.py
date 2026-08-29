from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import (
    Channel,
    ChannelAnalysisReport,
    ChannelAudienceProfile,
    ChannelDnaVersion,
    ChannelInitializationDraft,
    ChannelKeyword,
    ChannelPinnedCommentTemplate,
    ChannelPlaylist,
    ChannelProfile,
)
from zhiju.schemas.channel import ChannelInitializationDraftUpsert
from zhiju.services.channel import (
    apply_channel_initialization_draft,
    get_channel_initialization_draft,
    upsert_channel_initialization_draft,
)


ROOT = Path(__file__).resolve().parents[2]


def test_channel_initialization_draft_contract_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    methods = paths["/api/v3/channels/{channel_id}/initialization-draft"]

    assert {"get", "put"}.issubset(methods)
    assert "post" in paths["/api/v3/channels/{channel_id}/initialization-draft/apply"]
    assert {
        "description",
        "keywords",
        "tags",
        "avatar_prompt",
        "banner_prompt",
        "pinned_comment",
        "title_template",
        "popup_scheme",
        "playlists",
        "initial_audience",
        "initial_analysis",
        "operating_reference",
    }.issubset(ChannelInitializationDraftUpsert.model_fields)


def test_channel_initialization_draft_can_be_saved_without_rules_or_ai() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-DRAFT-{suffix}",
            original_name=f"频道-{suffix}",
            timezone="Asia/Shanghai",
            status="new",
        )
        session.add(channel)
        session.commit()

        saved = upsert_channel_initialization_draft(
            session,
            channel.id,
            ChannelInitializationDraftUpsert(
                description="频道说明草稿",
                keywords=["逆袭", "短剧"],
                playlists=["复仇逆袭", "豪门情感", "女性成长"],
                initial_analysis="初始分析草稿",
            ),
        )
        loaded = get_channel_initialization_draft(session, channel.id)

        assert isinstance(saved, ChannelInitializationDraft)
        assert loaded is not None
        assert loaded.output_draft["description"] == "频道说明草稿"
        assert loaded.output_draft["keywords"] == ["逆袭", "短剧"]
        assert loaded.output_draft["playlists"] == ["复仇逆袭", "豪门情感", "女性成长"]
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_channel_initialization_draft_applies_existing_modules_once() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-APPLY-{suffix}",
            original_name=f"频道-{suffix}",
            default_language="id",
            timezone="Asia/Shanghai",
            status="new",
        )
        session.add(channel)
        session.commit()
        upsert_channel_initialization_draft(
            session,
            channel.id,
            ChannelInitializationDraftUpsert(
                description="正式频道说明",
                keywords=["逆袭", "短剧"],
                tags=["女频"],
                avatar_prompt="头像词",
                pinned_comment="置顶评论",
                title_template="标题模板",
                popup_scheme="弹框方案",
                playlists=["复仇逆袭", "女性成长", "豪门情感"],
                initial_analysis="保留在草稿的分析",
            ),
        )

        first = apply_channel_initialization_draft(session, channel.id)
        second = apply_channel_initialization_draft(session, channel.id)

        profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel.id))
        assert profile.description == "正式频道说明"
        assert profile.avatar_prompt == "头像词"
        assert profile.title_template == "标题模板"
        assert first["applied_modules"] == [
            "频道说明与装修",
            "关键词与标签",
            "置顶评论",
            "播放列表",
            "初始分析报告",
        ]
        assert first["retained_draft_modules"] == []
        assert second["created_keywords"] == 0
        assert second["created_playlists"] == 0
        assert session.scalar(select(func.count()).select_from(ChannelKeyword).where(ChannelKeyword.channel_id == channel.id)) == 3
        assert session.scalar(select(func.count()).select_from(ChannelPinnedCommentTemplate).where(ChannelPinnedCommentTemplate.channel_id == channel.id)) == 1
        assert session.scalar(select(func.count()).select_from(ChannelPlaylist).where(ChannelPlaylist.channel_id == channel.id)) == 3
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_channel_initialization_draft_versions_analysis_and_operating_reference_once() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-INIT-VERSION-{suffix}",
            original_name=f"频道-{suffix}",
            default_language="id",
            default_genre="女频逆袭",
            timezone="Asia/Jakarta",
            status="new",
        )
        session.add(channel)
        session.commit()
        upsert_channel_initialization_draft(
            session,
            channel.id,
            ChannelInitializationDraftUpsert(
                initial_audience="25-44 岁女性，偏好快节奏逆袭。",
                initial_analysis="频道初始定位为女频逆袭短剧。",
                operating_reference="排期优先使用高冲突、强情绪的女频剧。",
            ),
        )

        first = apply_channel_initialization_draft(session, channel.id)
        second = apply_channel_initialization_draft(session, channel.id)

        reports = list(
            session.scalars(
                select(ChannelAnalysisReport).where(ChannelAnalysisReport.channel_id == channel.id)
            )
        )
        profiles = list(session.scalars(select(ChannelAudienceProfile)))
        dna_versions = list(
            session.scalars(
                select(ChannelDnaVersion).where(ChannelDnaVersion.channel_id == channel.id)
            )
        )
        assert len(reports) == 1
        assert reports[0].report_type == "initial"
        assert reports[0].summary == "频道初始定位为女频逆袭短剧。"
        assert len(profiles) == 1
        assert profiles[0].summary == "25-44 岁女性，偏好快节奏逆袭。"
        assert len(dna_versions) == 1
        assert dna_versions[0].status == "active"
        assert dna_versions[0].analysis_report_id == reports[0].id
        assert dna_versions[0].reference_summary == "排期优先使用高冲突、强情绪的女频剧。"
        assert first["analysis_report_id"] == second["analysis_report_id"] == reports[0].id
        assert first["dna_version_id"] == second["dna_version_id"] == dna_versions[0].id
        assert first["retained_draft_modules"] == []
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_channel_initialization_draft_change_creates_new_formal_versions() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-INIT-CHANGE-{suffix}",
            original_name=f"频道-{suffix}",
            default_language="en",
            default_genre="豪门情感",
            timezone="Europe/London",
            status="new",
        )
        session.add(channel)
        session.commit()
        upsert_channel_initialization_draft(
            session,
            channel.id,
            ChannelInitializationDraftUpsert(
                initial_audience="初始画像 v1",
                initial_analysis="初始分析 v1",
                operating_reference="运营参考 v1",
            ),
        )
        first = apply_channel_initialization_draft(session, channel.id)

        upsert_channel_initialization_draft(
            session,
            channel.id,
            ChannelInitializationDraftUpsert(
                initial_audience="初始画像 v2",
                initial_analysis="初始分析 v2",
                operating_reference="运营参考 v2",
            ),
        )
        second = apply_channel_initialization_draft(session, channel.id)

        reports = list(
            session.scalars(
                select(ChannelAnalysisReport)
                .where(ChannelAnalysisReport.channel_id == channel.id)
                .order_by(ChannelAnalysisReport.version_number)
            )
        )
        dna_versions = list(
            session.scalars(
                select(ChannelDnaVersion)
                .where(ChannelDnaVersion.channel_id == channel.id)
                .order_by(ChannelDnaVersion.version_number)
            )
        )
        assert [report.summary for report in reports] == ["初始分析 v1", "初始分析 v2"]
        assert [version.reference_summary for version in dna_versions] == ["运营参考 v1", "运营参考 v2"]
        assert [version.status for version in dna_versions] == ["superseded", "active"]
        assert first["analysis_report_id"] != second["analysis_report_id"]
        assert first["dna_version_id"] != second["dna_version_id"]
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_channel_detail_exposes_initialization_workspace() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function channelInitializationDraftForm" in source
    assert 'data-action="edit-channel-initialization"' in source
    assert 'id="channelInitializationDraftForm"' in source
    assert "`/channels/${channelId}/initialization-draft`" in source
    assert 'data-action="apply-channel-initialization"' in source
    assert "确认把初始化草稿应用到正式频道配置" in source
