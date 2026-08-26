from fastapi.testclient import TestClient

from zhiju.app import app


def test_channel_pinned_comment_template_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    collection = "/api/v3/channels/{channel_id}/pinned-comment-templates"
    activation = (
        "/api/v3/channels/{channel_id}/pinned-comment-templates/"
        "{template_id}/activate"
    )

    assert {"get", "post"}.issubset(paths[collection])
    assert "post" in paths[activation]
