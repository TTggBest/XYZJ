from fastapi.testclient import TestClient
from pathlib import Path
from sqlalchemy.orm import Session
from uuid import uuid4

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import ChannelDramaType
from zhiju.schemas.settings import ChannelDramaTypeCreate, ChannelDramaTypeUpdate
from zhiju.services.settings import create_channel_drama_type, update_channel_drama_type


def test_channel_drama_type_model_contract() -> None:
    columns = ChannelDramaType.__table__.columns

    assert {"code", "name", "description", "sort_order", "status"}.issubset(
        columns.keys()
    )


def test_channel_drama_type_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert {"get", "post"}.issubset(
        paths["/api/v3/settings/channel-drama-types"]
    )
    assert "put" in paths["/api/v3/settings/channel-drama-types/{type_id}"]


def test_settings_page_exposes_channel_drama_types() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "assets" / "app.js"
    ).read_text(encoding="utf-8")

    assert '["dramaTypes", "短剧类型", "list-tree"]' in source
    assert 'api("/settings/channel-drama-types?include_disabled=true")' in source
    assert 'id="channelDramaTypeForm"' in source


def test_channel_drama_type_can_be_created_and_disabled() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        created = create_channel_drama_type(
            session,
            ChannelDramaTypeCreate(
                code=f"test-{suffix}", name=f"测试类型-{suffix}", sort_order=30
            ),
        )
        updated = update_channel_drama_type(
            session,
            created.id,
            ChannelDramaTypeUpdate(status="disabled", description="测试停用"),
        )

        assert updated.status == "disabled"
        assert updated.description == "测试停用"
    finally:
        session.close()
        transaction.rollback()
        connection.close()
