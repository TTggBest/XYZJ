import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from zhiju.app import app
from zhiju.schemas.channel import MediaAssetCreate


def test_media_asset_center_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert {"get", "post"}.issubset(paths["/api/v3/media-assets"])
    assert {"get", "patch"}.issubset(paths["/api/v3/media-assets/{asset_id}"])
    assert "patch" in paths["/api/v3/media-assets/{asset_id}/status"]
    assert "delete" in paths["/api/v3/media-assets/{asset_id}"]


def test_ready_image_requires_image_metadata() -> None:
    with pytest.raises(ValidationError):
        MediaAssetCreate(
            storage_key="covers/missing-size.png",
            asset_type="image",
            asset_role="thumbnail",
            mime_type="image/png",
            sha256="a" * 64,
            file_size_bytes=10,
            operation_package_id="package-id",
            status="ready",
        )


def test_media_asset_contract_exposes_purpose_and_public_url() -> None:
    document = TestClient(app).get("/openapi.json").json()
    serialized = str(document)

    assert "asset_role" in serialized
    assert "public_url" in serialized
