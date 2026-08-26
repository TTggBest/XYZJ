from fastapi.testclient import TestClient

from zhiju.app import app


def test_authorization_control_plane_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert {"get", "post"}.issubset(paths["/api/v3/oauth-grants"])
    assert "get" in paths["/api/v3/accounts/{account_id}/oauth-grants"]
    assert "post" in paths["/api/v3/channel-authorizations/verify"]
    assert "get" in paths["/api/v3/channels/{channel_id}/authorizations"]
    assert "get" in paths["/api/v3/authorization-events"]


def test_oauth_contract_never_exposes_token_fields() -> None:
    document = TestClient(app).get("/openapi.json").json()
    serialized = str(document).lower()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "credential_ref" in serialized


def test_youtube_sync_start_requires_a_verified_authorization() -> None:
    document = TestClient(app).get("/openapi.json").json()
    schema = document["components"]["schemas"]["SyncStart"]
    assert "authorization_id" in schema["required"]
