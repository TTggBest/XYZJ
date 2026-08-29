from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from uuid import uuid4

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import Channel, ChannelDramaType
from zhiju.schemas.channel import ChannelDetailRead, ChannelHubUpdate
from zhiju.services.channel import update_channel_hub


def test_channel_hub_update_excludes_read_only_identity_fields() -> None:
    fields = ChannelHubUpdate.model_fields

    assert {
        "chinese_meaning",
        "default_genre",
        "drama_type",
        "description",
        "positioning",
        "avatar_prompt",
        "banner_prompt",
        "popup_scheme",
        "title_template",
        "fixed_symbol",
    }.issubset(fields)
    assert "original_name" not in fields
    assert "youtube_channel_id" not in fields
    assert "youtube_channel_url" not in fields


def test_channel_hub_detail_exposes_existing_operational_modules() -> None:
    fields = ChannelDetailRead.model_fields

    assert {
        "pinned_comment_templates",
        "playlists",
        "branding_assets",
        "drama_types",
        "relevant_skills",
    }.issubset(fields)


def test_channel_hub_update_route_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "put" in paths["/api/v3/channels/{channel_id}/hub"]


def test_channel_hub_update_persists_editable_fields() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        drama_type = ChannelDramaType(
            code=f"hub-{suffix}", name=f"频道类型-{suffix}", status="active"
        )
        channel = Channel(
            youtube_channel_id=f"UC-HUB-{suffix}",
            original_name=f"频道-{suffix}",
            timezone="Asia/Shanghai",
            status="active",
        )
        session.add_all([drama_type, channel])
        session.commit()

        detail = update_channel_hub(
            session,
            channel.id,
            ChannelHubUpdate(
                chinese_meaning="测试频道",
                default_genre="逆袭",
                drama_type=drama_type.code,
                description="频道说明",
                avatar_prompt="头像词",
                title_template="标题模板",
            ),
        )

        assert detail["channel"].original_name == channel.original_name
        assert detail["channel"].chinese_meaning == "测试频道"
        assert detail["channel"].drama_type == drama_type.code
        assert detail["profile"].description == "频道说明"
        assert detail["profile"].avatar_prompt == "头像词"
        assert detail["profile"].title_template == "标题模板"
    finally:
        session.close()
        transaction.rollback()
        connection.close()
