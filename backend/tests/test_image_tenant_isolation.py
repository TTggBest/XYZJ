"""Two-tenant HTTP/ORM file boundaries; SQLite is only an ORM test fixture."""
from dataclasses import replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from test_production_tenant_isolation import store, PRINCIPAL
from zhiju import auth_context, database
from zhiju.app import create_app
from zhiju.database import TenantSession
from zhiju.models import (ImageProcessingRun, ImageProcessingItem, ImageWorkspaceSetting,
    ChannelLogoProfile, MediaAsset, ProductionBatch, PackageArtifact, PackageTitle, PackageCoverVariant)
from zhiju.services import image_processing, package_outputs


def png(template=False):
    image = Image.new("RGB", (120, 80), "white")
    if template:
        draw = ImageDraw.Draw(image)
        draw.rectangle((5, 5, 25, 20), fill="red")
        draw.rectangle((90, 5, 115, 20), fill="blue")
    result = BytesIO()
    image.save(result, "PNG")
    return result.getvalue()


@pytest.fixture
def image_store(store, tmp_path):
    with Session(store) as session:
        for key in ("a", "b"):
            tenant = f"tenant-{key}"
            setting = ImageWorkspaceSetting(id=f"workspace-{key}", tenant_id=tenant,
                root_path=f"tenants/{tenant}/workspace", persistent_dir_name="系统素材", output_dir_name="用户产物")
            run = ImageProcessingRun(id=f"run-{key}", batch_id=f"batch-{key}", status="partially_classified",
                total_files=1, unmatched_files=1, manifest_path=f"tenants/{tenant}/report.json")
            item = ImageProcessingItem(id=f"item-{key}", run_id=f"run-{key}", original_filename=f"secret-{key}.png",
                stored_path=f"tenants/{tenant}/unmatched.png", match_status="unmatched")
            run.tenant_id = item.tenant_id = tenant
            session.add_all([setting, run, item])
            asset = session.get(MediaAsset, f"asset-{key}")
            asset.storage_key = f"tenants/{tenant}/asset.png"
            asset.sha256 = "a" * 64
            asset.mime_type = "image/png"
            root = tmp_path / setting.root_path
            path = root / asset.storage_key
            path.parent.mkdir(parents=True)
            path.write_bytes(png())
            session.add(ChannelLogoProfile(id=f"logo-{key}", tenant_id=tenant, channel_id=f"channel-{key}",
                status="calibrated", left_logo_path=f"tenants/{tenant}/left.png",
                right_logo_path=f"tenants/{tenant}/right.png", template_path=f"tenants/{tenant}/template.png",
                config_path=f"tenants/{tenant}/logo.json", canvas_width=120, canvas_height=80,
                calibrated_at=datetime(2026, 9, 13)))
        session.commit()
    return store


@pytest.fixture
def image_client(image_store, monkeypatch, tmp_path):
    app = create_app()
    def unscoped():
        with Session(image_store) as session:
            yield session
    app.dependency_overrides[database.get_db] = unscoped
    app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
    monkeypatch.setattr(database.database_router, "get_active_engine", lambda: image_store)
    monkeypatch.setattr(image_processing, "get_settings", lambda: SimpleNamespace(shared_root=tmp_path))
    monkeypatch.setattr(package_outputs, "get_settings", lambda: SimpleNamespace(artifact_root=tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("path,field,want", [
    ("/media-assets", "id", "asset-a"), ("/media-assets/contexts", "package_id", "package-a"),
    ("/channels/logo-profiles", "id", "logo-a"), ("/image-processing/batches", "id", "batch-a"),
    ("/image-processing/runs", "id", "run-a"),
])
def test_lists_include_only_current_tenant(image_client, path, field, want):
    response = image_client.get(f"/api/v3{path}?tenant_id=tenant-b", headers={"X-Tenant-ID": "tenant-b"})
    assert response.status_code == 200, response.text
    assert [row[field] for row in response.json()] == [want]


def test_run_history_and_unmatched_items_are_scoped(image_client):
    response = image_client.get("/api/v3/image-processing/runs/history")
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert page["items"][0]["items"][0]["original_filename"] == "secret-a.png"


@pytest.mark.parametrize("method,path", [
    ("GET", "/media-assets/asset-b"), ("GET", "/media-assets/asset-b/content"),
    ("GET", "/media-assets/asset-b/thumbnail"), ("POST", "/media-assets/asset-b/reveal"),
    ("POST", "/image-processing/runs/run-b/generate-logo"),
    ("GET", "/image-processing/batches/batch-b/asset-coverage"),
    ("GET", "/image-processing/runs/history?batch_id=batch-b"),
    ("GET", "/media-assets?batch_id=batch-b"),
    ("GET", "/media-assets?operation_package_id=package-b"),
])
def test_known_foreign_ids_are_404(image_client, method, path):
    response = image_client.request(method, f"/api/v3{path}")
    assert response.status_code == 404, response.text


def test_import_and_logo_profile_reject_foreign_parent_before_writing(image_client, image_store):
    response = image_client.post("/api/v3/image-processing/import", data={"batch_id": "batch-b"},
                                 files={"files": ("unknown.png", png(), "image/png")})
    assert response.status_code == 404, response.text
    response = image_client.put("/api/v3/channels/channel-b/logo-profile", files={
        name: ("image.png", png(True), "image/png") for name in ("left_logo", "right_logo", "template")})
    assert response.status_code == 404, response.text
    with Session(image_store) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(ImageProcessingRun)) == 2


@pytest.mark.parametrize("key", ["tenants/tenant-b/asset.png", "old/asset.png",
                                  "tenants/tenant-a/../tenant-b/asset.png"])
def test_register_rejects_foreign_or_legacy_storage_key(image_client, key):
    response = image_client.post("/api/v3/media-assets", json={"storage_key": key,
        "storage_provider": "local", "asset_type": "image", "asset_role": "other",
        "sha256": "a" * 64, "file_size_bytes": 10, "status": "pending"})
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("key", ["tenants/tenant-b/other.png", "old/asset.png"])
def test_owned_asset_cannot_resolve_foreign_or_legacy_path(image_client, image_store, key):
    with Session(image_store) as session:
        session.get(MediaAsset, "asset-a").storage_key = key
        session.commit()
    for suffix in ("content", "thumbnail", "reveal"):
        response = image_client.request("POST" if suffix == "reveal" else "GET", f"/api/v3/media-assets/asset-a/{suffix}")
        assert response.status_code == 404, response.text


def test_owned_content_and_import_write_prefixed_metadata(image_client, image_store, tmp_path):
    assert image_client.get("/api/v3/media-assets/asset-a/content").status_code == 200
    response = image_client.post("/api/v3/image-processing/import", data={"batch_id": "batch-a"}, files=[
        ("files", ("DR-a_07_community1_1x1.png", png(), "image/png")),
        ("files", ("unknown.png", png(), "image/png"))])
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["manifest_path"].startswith("tenants/tenant-a/")
    assert len(result["items"]) == 2
    assert {item["match_status"] for item in result["items"]} == {"matched", "unmatched"}
    with Session(image_store) as session:
        run = session.get(ImageProcessingRun, result["id"])
        assert run.tenant_id == "tenant-a"
        for item in session.scalars(sa.select(ImageProcessingItem).where(ImageProcessingItem.run_id == run.id)):
            assert item.tenant_id == "tenant-a" and item.stored_path.startswith("tenants/tenant-a/")
        assets = session.scalars(sa.select(MediaAsset).where(MediaAsset.id.not_in(["asset-a", "asset-b"]))).all()
        assert len(assets) == 1 and assets[0].tenant_id == "tenant-a"
        assert assets[0].storage_key.startswith("tenants/tenant-a/")


def test_workspace_is_per_tenant_and_rejects_foreign_root(image_client, image_store):
    assert image_client.get("/api/v3/settings/image-workspace").json()["id"] == "workspace-a"
    response = image_client.put("/api/v3/settings/image-workspace", json={"root_path": "tenants/tenant-a/new"})
    assert response.status_code == 200, response.text
    for path in ("tenants/tenant-b/workspace", "/tmp/arbitrary", "legacy"):
        assert image_client.put("/api/v3/settings/image-workspace", json={"root_path": path}).status_code == 404
    with Session(image_store) as session:
        assert session.get(ImageWorkspaceSetting, "workspace-b").root_path == "tenants/tenant-b/workspace"
        assert session.scalar(sa.select(sa.func.count()).select_from(ImageWorkspaceSetting)) == 2


def test_cached_foreign_run_or_asset_cannot_bypass_service_lookup(image_store):
    with Session(image_store) as plain:
        objects = [plain.get(ImageProcessingRun, "run-b"), plain.get(MediaAsset, "asset-b")]
        plain.expunge_all()
    with TenantSession(bind=image_store, info={"tenant_id": "tenant-a"}) as session:
        session.add_all(objects)
        for operation in (lambda: image_processing.generate_logos(session, "run-b"),
                          lambda: image_processing.resolve_media_asset_file(session, "asset-b")):
            with pytest.raises(HTTPException) as exc:
                operation()
            assert exc.value.status_code == 404


def test_logo_upload_and_generation_write_tenant_paths(image_client, image_store):
    response = image_client.put("/api/v3/channels/channel-a/logo-profile", files={
        name: ("image.png", png(True), "image/png") for name in ("left_logo", "right_logo", "template")})
    assert response.status_code == 200, response.text
    for key in ("left_logo_path", "right_logo_path", "template_path", "config_path"):
        assert response.json()[key].startswith("tenants/tenant-a/")
    response = image_client.post("/api/v3/image-processing/import", data={"batch_id": "batch-a"},
        files={"files": ("DR-a_02_title1_16x9.png", png(), "image/png")})
    assert response.status_code == 201, response.text
    response = image_client.post(f"/api/v3/image-processing/runs/{response.json()['id']}/generate-logo")
    assert response.status_code == 200, response.text
    assert response.json()["generated_files"] == 1
    assert response.json()["items"][0]["output_path"].startswith("tenants/tenant-a/")


def test_merge_artifact_keys_include_tenant_prefix(image_client, image_store, tmp_path):
    with TenantSession(bind=image_store, info={"tenant_id": "tenant-a"}) as session:
        for number in (1, 2, 3):
            title_id = "title-a" if number == 1 else f"title-{number}-a"
            if number != 1:
                session.add(PackageTitle(id=title_id, package_id="package-a", variant_number=number,
                    localized_title=f"title {number}", selected=True))
            for ratio in ("4:5", "16:9"):
                if number == 1 and ratio == "16:9":
                    continue
                session.add(PackageCoverVariant(package_id="package-a", title_id=title_id,
                    aspect_ratio=ratio, creative_prompt="prompt", selected=True))
        session.commit()
    response = image_client.post("/api/v3/packages/package-a/merge")
    assert response.status_code == 200, response.text
    with Session(image_store) as session:
        artifacts = session.scalars(sa.select(PackageArtifact).where(
            PackageArtifact.package_id == "package-a", PackageArtifact.status == "ready")).all()
        assert len(artifacts) == 2
        for artifact in artifacts:
            assert artifact.storage_key.startswith("tenants/tenant-a/")
            assert (tmp_path / artifact.storage_key).is_file()


def test_default_legacy_reconcile_reads_old_file_and_registers_prefixed_copy(image_store, monkeypatch, tmp_path):
    default = "00000000-0000-4000-8000-000000000001"
    from zhiju.models.base import TenantOwnedMixin
    with Session(image_store) as session:
        for mapper in sa.inspect(ImageProcessingItem).registry.mappers:
            model = mapper.class_
            if issubclass(model, TenantOwnedMixin):
                for obj in session.scalars(sa.select(model).where(model.tenant_id == "tenant-a")):
                    obj.tenant_id = default
        setting = session.get(ImageWorkspaceSetting, "workspace-a")
        setting.root_path = str(tmp_path / "legacy")
        item = session.get(ImageProcessingItem, "item-a")
        item.stored_path = "old/community.png"
        item.match_status = "matched"
        item.image_role = "07_社群1_1x1"
        item.package_id = "package-a"
        item.channel_id = "channel-a"
        item.drama_id = "drama-a"
        session.commit()
    path = tmp_path / "legacy/old/community.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(png())
    monkeypatch.setattr(image_processing, "get_settings", lambda: SimpleNamespace(shared_root=tmp_path))
    with TenantSession(bind=image_store, info={"tenant_id": default}) as session:
        result = image_processing.reconcile_processing_assets(session)
        assert result.registered_assets == 1
        asset = session.scalar(sa.select(MediaAsset).where(MediaAsset.id.not_in(["asset-a", "asset-b"])))
        assert asset.storage_key.startswith(f"tenants/{default}/")
        assert (tmp_path / "legacy" / asset.storage_key).read_bytes() == path.read_bytes()


@pytest.fixture
def migration():
    root = Path(__file__).resolve().parents[2]
    config = Config(root / "alembic.ini")
    config.set_main_option("script_location", str(root / "backend/alembic"))
    revision = next((r for r in ScriptDirectory.from_config(config).walk_revisions()
                     if r.revision == "f5b8c1d6e054"), None)
    return revision.module if revision else None


@pytest.fixture
def legacy_rows():
    rows = {name: [{"id": key, "tenant_id": f"tenant-{key}"} for key in ("a", "b")]
            for name in ("channels", "dramas", "production_batches", "image_workspace_settings")}
    rows["operation_packages"] = [{"id": key, "tenant_id": f"tenant-{key}", "channel_id": key,
        "drama_id": key, "batch_id": key, "schedule_id": key} for key in ("a", "b")]
    rows["channel_schedule_entries"] = [{"id": key, "tenant_id": f"tenant-{key}", "channel_id": key, "drama_id": key} for key in ("a", "b")]
    rows["media_assets"] = [{"id": key, "tenant_id": f"tenant-{key}", "channel_id": key,
        "operation_package_id": key, "storage_key": f"{key}.png"} for key in ("a", "b")]
    rows["image_processing_runs"] = [{"id": key, "batch_id": key} for key in ("a", "b")]
    rows["image_processing_items"] = [{"id": key, "run_id": key, "package_id": key, "channel_id": key,
        "drama_id": key, "schedule_id": key, "stored_path": f"{key}.png", "output_path": None} for key in ("a", "b")]
    rows["image_processing_items"].append({"id": "unmatched", "run_id": "a", "package_id": None,
        "channel_id": None, "drama_id": None, "schedule_id": None, "stored_path": "unmatched.png", "output_path": None})
    return rows


def test_migration_derives_matched_and_unmatched_owners(migration, legacy_rows):
    assert migration is not None, "Task 7 migration is missing"
    owners = migration.validate_owners(legacy_rows)
    assert owners["image_processing_runs"] == {"a": "tenant-a", "b": "tenant-b"}
    assert owners["image_processing_items"] == {"a": "tenant-a", "b": "tenant-b", "unmatched": "tenant-a"}


@pytest.mark.parametrize("table,column,value", [
    ("image_processing_runs", "batch_id", "missing"), ("image_processing_items", "run_id", "missing"),
    *[("image_processing_items", col, val) for col in ("package_id", "channel_id", "drama_id", "schedule_id") for val in ("missing", "b")],
    ("media_assets", "tenant_id", "tenant-b"), ("media_assets", "storage_key", "b.png"),
    ("operation_packages", "batch_id", "b"), ("channel_schedule_entries", "channel_id", "b"),
    ("image_workspace_settings", "tenant_id", None),
])
def test_migration_rejects_inconsistent_parent_chains(migration, legacy_rows, table, column, value):
    assert migration is not None, "Task 7 migration is missing"
    legacy_rows[table][0][column] = value
    with pytest.raises(RuntimeError):
        migration.validate_owners(legacy_rows)


def test_migration_rejects_duplicate_workspace_before_any_ddl(migration, legacy_rows, monkeypatch):
    assert migration is not None, "Task 7 migration is missing"
    legacy_rows["image_workspace_settings"].append({"id": "duplicate", "tenant_id": "tenant-a"})
    ops = Mock()
    monkeypatch.setattr(migration, "op", ops)
    monkeypatch.setattr(migration, "load_rows", lambda connection: legacy_rows)
    with pytest.raises(RuntimeError):
        migration.upgrade()
    assert ops.method_calls == [("get_bind", (), {})]
