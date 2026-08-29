from pathlib import Path

from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.services.settings import CHANNEL_INITIALIZATION_MODULES


ROOT = Path(__file__).resolve().parents[2]


def test_channel_initialization_modules_cover_planned_outputs() -> None:
    module_keys = {item[0] for item in CHANNEL_INITIALIZATION_MODULES}

    assert module_keys == {
        "description",
        "keywords_tags",
        "avatar_prompt",
        "banner_prompt",
        "pinned_comment",
        "title_template",
        "popup_scheme",
        "playlists",
        "initial_audience",
        "initial_analysis",
        "operating_reference",
    }


def test_channel_initialization_rules_route_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/settings/channel-initialization-rules"]


def test_settings_page_exposes_channel_initialization_rules() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert '["channelInitialization", "初始化规则", "wand-sparkles"]' in source
    assert 'api("/settings/channel-initialization-rules")' in source
    assert "初始化生成只使用当前已发布版本" in source
    assert 'data-action="go-skills"' in source
