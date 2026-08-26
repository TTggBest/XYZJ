from fastapi.testclient import TestClient

from zhiju.app import app


def test_health_reaches_mysql() -> None:
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["database"]["ok"] is True


def test_identity_lists_start_from_database() -> None:
    client = TestClient(app)
    assert client.get("/api/v3/accounts").status_code == 200
    assert client.get("/api/v3/channels").status_code == 200


def test_root_serves_management_ui() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "筱宇智矩" in response.text
    assert client.get("/assets/app.js").status_code == 200
