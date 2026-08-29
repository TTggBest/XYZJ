from fastapi.testclient import TestClient
from pathlib import Path

from zhiju.app import app
from zhiju.models import ChannelDramaType


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
