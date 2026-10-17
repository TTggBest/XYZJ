from pathlib import Path

from fastapi.testclient import TestClient

from zhiju.app import app


def test_authorization_control_plane_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert {"get", "post"}.issubset(paths["/api/v3/oauth-grants"])
    assert "get" in paths["/api/v3/accounts/{account_id}/oauth-grants"]
    assert "post" in paths["/api/v3/channel-authorizations/verify"]
    assert "get" in paths["/api/v3/channels/{channel_id}/authorizations"]
    assert "get" in paths["/api/v3/authorization-events"]
    assert "get" in paths["/api/v3/settings/youtube-oauth"]
    assert "post" in paths["/api/v3/settings/youtube-oauth/import-legacy"]
    assert "post" in paths["/api/v3/channels/{channel_id}/youtube-authorization/start"]
    assert "post" in paths["/api/v3/youtube/channel-imports/start"]
    assert "get" in paths["/api/v3/youtube/channel-imports/{import_session_id}"]
    assert "post" in paths["/api/v3/youtube/channel-imports/{import_session_id}/commit"]
    assert "get" in paths["/api/v3/youtube/oauth/callback"]


def test_oauth_contract_never_exposes_token_fields() -> None:
    document = TestClient(app).get("/openapi.json").json()
    serialized = str(document).lower()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized
    assert "credential_ref" in serialized


def test_youtube_sync_start_requires_a_verified_authorization() -> None:
    document = TestClient(app).get("/openapi.json").json()
    schema = document["components"]["schemas"]["SyncStart"]
    assert "authorization_id" in schema["required"]


def test_frontend_exposes_oauth_client_import_and_per_channel_authorization() -> None:
    app_js = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "导入旧版凭证" in app_js
    assert 'data-action="authorize-youtube-channel"' in app_js
    assert "授权 YouTube" in app_js
    assert "youtube-auth-complete" in app_js


def test_cloud_frontend_uses_oauth_first_multi_channel_import() -> None:
    app_js = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(
        encoding="utf-8"
    )

    assert 'data-action="start-youtube-channel-import"' in app_js
    assert "youtube-channel-import-ready" in app_js
    assert 'id="youtubeChannelImportForm"' in app_js
    assert "data-import-candidate" in app_js
    assert "data-import-country" in app_js
    assert "recommended_language" in app_js
    assert "recommended_timezone" in app_js
    assert "/youtube/channel-imports/${encodeURIComponent(importSessionId)}/commit" in app_js


def test_channel_list_shows_youtube_identity_and_chinese_language_name() -> None:
    app_js = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "item.youtube_avatar_url" in app_js
    assert 'data-action="copy-channel-name"' in app_js
    assert 'data-value="${esc(item.original_name)}"' in app_js
    assert "item.operational_name !== item.original_name" in app_js
    assert 'id: "印度尼西亚语"' in app_js
    assert '"pt-BR": "巴西葡萄牙语"' in app_js


def test_channel_overview_exposes_fields_needed_for_sorting_and_audience_filtering() -> None:
    document = TestClient(app).get("/openapi.json").json()
    properties = document["components"]["schemas"]["ChannelOverview"]["properties"]

    assert "created_at" in properties
    assert "channel_type" in properties
