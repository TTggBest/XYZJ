from fastapi.testclient import TestClient

from zhiju.app import app


def test_integration_management_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert {"get", "post"}.issubset(paths["/api/v3/integrations"])
    assert {"get", "post"}.issubset(
        paths["/api/v3/integrations/{integration_id}/accounts"]
    )
    assert {"get", "put"}.issubset(
        paths["/api/v3/integration-accounts/{account_id}/credentials"]
    )
    assert "post" in paths["/api/v3/integration-accounts/{account_id}/verify"]


def test_integration_contract_accepts_references_but_not_plaintext_secrets() -> None:
    document = TestClient(app).get("/openapi.json").json()
    serialized = str(document).lower()
    assert "secret_reference" in serialized
    assert "secret_value" not in serialized
    assert "bot_token" not in serialized
    assert "api_key" not in serialized
