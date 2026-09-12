from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from zhiju import models
from zhiju.app import app
from zhiju.database import database_router
from zhiju.database import TenantSession
from test_image_processing_contract import image_orm_database
from zhiju.schemas.channel import MediaAssetCreate
from zhiju.services.channel import list_media_assets


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


def test_media_assets_can_be_filtered_by_production_batch() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = TenantSession(bind=connection, join_transaction_mode="create_savepoint", info={"tenant_id": "contract-tenant"})
    try:
        channel = models.Channel(
            youtube_channel_id=f"UC-ASSET-BATCH-{suffix}",
            original_name=f"素材批次频道-{suffix}",
            default_language="zh",
            timezone="Asia/Shanghai",
            status="active",
        )
        drama = models.Drama(
            drama_number=-int(suffix[:8], 16),
            drama_code=f"ASSET-BATCH-{suffix}",
            chinese_title=f"素材批次剧目-{suffix}",
            normalized_title=f"素材批次剧目-{suffix}".casefold(),
            source_type="manual",
            status="active",
        )
        batches = [
            models.ProductionBatch(
                batch_number=f"FS-ASSET-A-{suffix}",
                production_date=date(2026, 9, 10),
                source="native",
                status="active",
            ),
            models.ProductionBatch(
                batch_number=f"FS-ASSET-B-{suffix}",
                production_date=date(2026, 9, 11),
                source="native",
                status="active",
            ),
        ]
        session.add_all([channel, drama, *batches])
        session.flush()

        assets = []
        for index, batch in enumerate(batches, start=1):
            task = models.OperationTask(
                batch_id=batch.id,
                channel_id=channel.id,
                drama_id=drama.id,
                task_date=batch.production_date,
                target_publish_date=batch.production_date,
                source="manual",
                status="completed",
                idempotency_key=f"asset-batch-task-{suffix}-{index}",
            )
            session.add(task)
            session.flush()
            work_order = models.WorkOrder(
                task_id=task.id,
                batch_id=batch.id,
                channel_id=channel.id,
                drama_id=drama.id,
                production_date=batch.production_date,
                target_publish_date=batch.production_date,
                status="completed",
            )
            session.add(work_order)
            session.flush()
            package = models.OperationPackage(
                work_order_id=work_order.id,
                batch_id=batch.id,
                channel_id=channel.id,
                drama_id=drama.id,
                version_number=1,
                status="approved",
            )
            session.add(package)
            session.flush()
            asset = models.MediaAsset(
                channel_id=channel.id,
                operation_package_id=package.id,
                storage_provider="local",
                storage_key=f"用户产物/{suffix}/{index}/cover.webp",
                original_filename="cover.webp",
                asset_type="image",
                asset_role="thumbnail",
                mime_type="image/webp",
                sha256=str(index) * 64,
                width=1280,
                height=720,
                file_size_bytes=100,
                status="ready",
            )
            session.add(asset)
            assets.append(asset)
        session.commit()

        rows = list_media_assets(session, batch_id=batches[0].id, limit=500)

        assert [row.id for row in rows] == [assets[0].id]
    finally:
        session.close()
        transaction.rollback()
        connection.close()
