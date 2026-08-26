from fastapi.testclient import TestClient

from zhiju.app import app


def test_channel_analysis_report_history_route_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v3/channels/{channel_id}/analysis-reports" in paths
    assert "get" in paths["/api/v3/channels/{channel_id}/analysis-reports"]
    assert "/api/v3/channels/{channel_id}/analysis-reports/{report_id}" in paths
