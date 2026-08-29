from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import Channel, ChannelInitializationDraft
from zhiju.schemas.channel import ChannelInitializationDraftUpsert
from zhiju.services.channel import get_channel_initialization_draft, upsert_channel_initialization_draft


ROOT = Path(__file__).resolve().parents[2]


def test_channel_initialization_draft_contract_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    methods = paths["/api/v3/channels/{channel_id}/initialization-draft"]

    assert {"get", "put"}.issubset(methods)
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


def test_channel_detail_exposes_initialization_workspace() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function channelInitializationDraftForm" in source
    assert 'data-action="edit-channel-initialization"' in source
    assert 'id="channelInitializationDraftForm"' in source
    assert "`/channels/${channelId}/initialization-draft`" in source
