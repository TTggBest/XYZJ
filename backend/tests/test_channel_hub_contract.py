from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.schemas.channel import ChannelDetailRead, ChannelHubUpdate


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
