from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from zhiju import permissions
from zhiju.auth_context import Principal, get_current_principal


@pytest.mark.parametrize(
    "deployment,device_role,platform_role,expected",
    [
        ("cloud", "worker", "super_admin", 200),
        ("cloud", "worker", None, 403),
        ("local", "worker", "super_admin", 403),
        ("local", "builder", "super_admin", 200),
    ],
)
def test_catalog_device_gate_allows_cloud_super_admin_only(
    monkeypatch, deployment, device_role, platform_role, expected
):
    monkeypatch.setattr(permissions, "get_settings", lambda: SimpleNamespace(
        deployment=deployment, device_role=device_role,
    ))
    principal = Principal(
        user_id="admin", tenant_id=None, membership_role=None,
        platform_role=platform_role, device_id=None,
        device_trust_level="untrusted", permissions=frozenset(),
    )
    app = FastAPI()
    app.dependency_overrides[get_current_principal] = lambda: principal

    @app.get("/catalog", dependencies=[Depends(permissions.require_builder_device)])
    def catalog():
        return {"available": True}

    response = TestClient(app).get("/catalog")
    assert response.status_code == expected
    if expected == 200:
        assert response.json() == {"available": True}
