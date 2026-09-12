from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy.orm import Session

from zhiju import auth_context, database
from zhiju.api import demo as demo_api, feishu_sync as feishu_api, integration as integration_api
from zhiju.auth_context import Principal
from zhiju.database import TenantSession
from zhiju.models import (
    Base,
    Channel,
    ChannelScheduleEntry,
    DemoDataBatch,
    DemoDataEntity,
    Drama,
    Integration,
    IntegrationAccount,
    IntegrationCredential,
    OperationPackage,
    OperationTask,
    ProductionBatch,
    WorkOrder,
    YoutubeVideo,
)
from zhiju.schemas.demo import DemoDataImportRequest
from zhiju.schemas.integration import IntegrationAccountCreate, IntegrationCredentialUpsert
from zhiju.services import demo, feishu_sync, integration
from zhiju.services.zhihe_progress_sync import sync_zhihe_progress


ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL_A = Principal(
    user_id="user-a", tenant_id="tenant-a", membership_role="owner",
    platform_role=None, device_id=None, device_trust_level="normal",
    permissions=frozenset(),
)


def _unique_columns(model) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }


def test_external_sync_models_use_tenant_owned_children_and_business_keys():
    assert issubclass(IntegrationCredential, Base)
    assert issubclass(DemoDataEntity, Base)
    assert hasattr(IntegrationCredential, "tenant_id")
    assert hasattr(DemoDataEntity, "tenant_id")
    assert ("tenant_id", "integration_id", "account_key") in _unique_columns(IntegrationAccount)
    assert ("tenant_id", "integration_account_id", "credential_type") in _unique_columns(IntegrationCredential)
    assert ("tenant_id", "batch_number") in _unique_columns(ProductionBatch)
    assert ("tenant_id", "idempotency_key") in _unique_columns(OperationTask)
    assert ("tenant_id", "batch_code") in _unique_columns(DemoDataBatch)
    assert ("tenant_id", "entity_type", "entity_id") in _unique_columns(DemoDataEntity)
    assert ("tenant_id", "normalized_title") in _unique_columns(Drama)


@pytest.fixture
def migration():
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    revision = next(
        (item for item in ScriptDirectory.from_config(config).walk_revisions()
         if item.revision == "b7d0e3f8a276"),
        None,
    )
    return revision.module if revision else None


@pytest.fixture
def legacy_sync_graph():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "integration_accounts", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36)),
        sa.Column("integration_id", sa.String(36)),
        sa.Column("account_key", sa.String(255)),
    )
    sa.Table(
        "integration_credentials", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("integration_account_id", sa.String(36)),
        sa.Column("credential_type", sa.String(60)),
    )
    sa.Table(
        "demo_data_batches", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36)),
        sa.Column("batch_code", sa.String(100)),
    )
    sa.Table(
        "demo_data_entities", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36)),
        sa.Column("entity_type", sa.String(80)),
        sa.Column("entity_id", sa.String(36)),
    )
    sa.Table(
        "feishu_sync_runs", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36)),
    )
    sa.Table(
        "production_batches", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36)),
        sa.Column("batch_number", sa.String(80)),
    )
    sa.Table(
        "operation_tasks", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36)),
        sa.Column("idempotency_key", sa.String(160)),
    )
    sa.Table(
        "dramas", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36)),
        sa.Column("normalized_title", sa.String(255)),
    )
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(metadata.tables["integration_accounts"].insert(), [
            {"id": "account-a", "tenant_id": "tenant-a", "integration_id": "feishu", "account_key": "shared"},
            {"id": "account-b", "tenant_id": "tenant-b", "integration_id": "feishu", "account_key": "shared"},
        ])
        connection.execute(metadata.tables["integration_credentials"].insert(), [
            {"id": "credential-a", "integration_account_id": "account-a", "credential_type": "token"},
            {"id": "credential-b", "integration_account_id": "account-b", "credential_type": "token"},
        ])
        connection.execute(metadata.tables["demo_data_batches"].insert(), [
            {"id": "batch-a", "tenant_id": "tenant-a", "batch_code": "shared-demo"},
            {"id": "batch-b", "tenant_id": "tenant-b", "batch_code": "shared-demo"},
        ])
        connection.execute(metadata.tables["demo_data_entities"].insert(), [
            {"id": "entity-a", "batch_id": "batch-a", "entity_type": "channel", "entity_id": "same-row"},
            {"id": "entity-b", "batch_id": "batch-b", "entity_type": "channel", "entity_id": "same-row"},
        ])
        for table, business_key in (("production_batches", "batch_number"), ("operation_tasks", "idempotency_key")):
            connection.execute(metadata.tables[table].insert(), [
                {"id": f"{table}-a", "tenant_id": "tenant-a", business_key: "shared-key"},
                {"id": f"{table}-b", "tenant_id": "tenant-b", business_key: "shared-key"},
            ])
        connection.execute(metadata.tables["feishu_sync_runs"].insert(), [
            {"id": "run-a", "tenant_id": "tenant-a"},
            {"id": "run-b", "tenant_id": "tenant-b"},
        ])
        connection.execute(metadata.tables["dramas"].insert(), [
            {"id": "drama-a", "tenant_id": "tenant-a", "normalized_title": "shared-drama"},
            {"id": "drama-b", "tenant_id": "tenant-b", "normalized_title": "shared-drama"},
        ])
        yield connection
    engine.dispose()


def _install_migration(monkeypatch, migration, connection):
    assert migration is not None, "Task 9 migration is missing"
    assert migration.down_revision == "a6c9d2e7f165"
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))


def test_migration_inherits_credential_and_demo_entity_tenant_and_accepts_cross_tenant_keys(
    migration, legacy_sync_graph, monkeypatch,
):
    _install_migration(monkeypatch, migration, legacy_sync_graph)
    owners = migration.validate_owners(migration.load_rows(legacy_sync_graph))
    assert owners["integration_credentials"] == {
        "credential-a": "tenant-a", "credential-b": "tenant-b",
    }
    assert owners["demo_data_entities"] == {
        "entity-a": "tenant-a", "entity-b": "tenant-b",
    }


@pytest.mark.parametrize("breakage", ["credential_orphan", "demo_orphan", "run_missing_tenant", "same_tenant_duplicate"])
def test_migration_rejects_unowned_or_duplicate_rows_before_ddl(
    migration, legacy_sync_graph, monkeypatch, breakage,
):
    _install_migration(monkeypatch, migration, legacy_sync_graph)
    if breakage == "credential_orphan":
        legacy_sync_graph.execute(sa.text(
            "UPDATE integration_credentials SET integration_account_id='missing' WHERE id='credential-a'"
        ))
    elif breakage == "demo_orphan":
        legacy_sync_graph.execute(sa.text(
            "UPDATE demo_data_entities SET batch_id='missing' WHERE id='entity-a'"
        ))
    elif breakage == "run_missing_tenant":
        legacy_sync_graph.execute(sa.text(
            "UPDATE feishu_sync_runs SET tenant_id=NULL WHERE id='run-a'"
        ))
    else:
        legacy_sync_graph.execute(sa.text(
            "UPDATE integration_accounts SET tenant_id='tenant-a' WHERE id='account-b'"
        ))
    with pytest.raises(RuntimeError):
        migration.validate_owners(migration.load_rows(legacy_sync_graph))
    assert "tenant_id" not in {
        column["name"] for column in sa.inspect(legacy_sync_graph).get_columns("integration_credentials")
    }
    assert "tenant_id" not in {
        column["name"] for column in sa.inspect(legacy_sync_graph).get_columns("demo_data_entities")
    }


@pytest.fixture
def store():
    engine = sa.create_engine(
        "sqlite://", poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    drama_number = iter(range(10_000, 20_000))

    def fill_sqlite_drama_number(_mapper, _connection, target):
        if target.drama_number is None:
            target.drama_number = next(drama_number)

    sa.event.listen(Drama, "before_insert", fill_sqlite_drama_number)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Integration(id="feishu", code="feishu", name="Feishu", provider_type="feishu", status="active"))
        session.commit()
    yield engine
    sa.event.remove(Drama, "before_insert", fill_sqlite_drama_number)
    engine.dispose()


def _tenant_session(store, tenant_id):
    return TenantSession(store, info={"tenant_id": tenant_id, "user_id": f"user-{tenant_id}", "permissions": frozenset()})


def test_same_integration_account_and_credential_key_can_exist_in_each_tenant(store):
    payload = IntegrationAccountCreate(account_key="shared", display_name="Shared", status="active")
    for tenant_id in ("tenant-a", "tenant-b"):
        with _tenant_session(store, tenant_id) as session:
            account = integration.create_integration_account(session, "feishu", payload)
            integration.upsert_integration_credential(session, account.id, IntegrationCredentialUpsert(
                credential_type="access_token", secret_reference=f"vault://{tenant_id}", status="active",
            ))
    with _tenant_session(store, "tenant-a") as session:
        accounts = integration.list_integration_accounts(session, "feishu")
        assert [(row.account_key, row.tenant_id) for row in accounts] == [("shared", "tenant-a")]
        with Session(store) as unscoped:
            foreign_account_id = unscoped.scalar(
                sa.select(IntegrationAccount.id).where(IntegrationAccount.tenant_id == "tenant-b")
            )
        with pytest.raises(integration.IntegrationNotFoundError):
            integration.list_integration_credentials(session, foreign_account_id)


def test_feishu_task_lookup_never_updates_matching_foreign_objects(store):
    row = {
        "剧名": "同名剧目", "频道": "同名频道", "频道昵称": "同名频道",
        "档期": "2026091512", "日期": "20260915", "是否需要社区": "0", "__source_row_number": "2",
    }
    with _tenant_session(store, "tenant-b") as session:
        task_b, channel_b, drama_b, batch_b, inserted = feishu_sync._ensure_task(session, row, completed=False)
        assert inserted
        foreign_ids = task_b.id, channel_b.id, drama_b.id, batch_b.id
        session.commit()
    with _tenant_session(store, "tenant-a") as session:
        task_a, channel_a, drama_a, batch_a, inserted = feishu_sync._ensure_task(session, row, completed=True)
        session.commit()
        assert inserted
        assert {task_a.id, channel_a.id, drama_a.id, batch_a.id}.isdisjoint(foreign_ids)
        assert {task_a.tenant_id, channel_a.tenant_id, drama_a.tenant_id, batch_a.tenant_id} == {"tenant-a"}
    with Session(store) as session:
        task_b = session.get(OperationTask, foreign_ids[0])
        assert task_b.status == "pending_dispatch"
        assert session.scalar(sa.select(sa.func.count()).select_from(Channel)) == 2
        assert session.scalar(sa.select(sa.func.count()).select_from(Drama)) == 2
        assert session.scalar(sa.select(sa.func.count()).select_from(ProductionBatch)) == 2
        assert session.scalar(sa.select(sa.func.count()).select_from(OperationTask)) == 2


def test_operation_package_sync_creates_a_complete_graph_per_tenant(store):
    row = {
        "剧名": "共享名剧目", "频道": "共享名频道", "频道昵称": "共享名频道",
        "档期": "2026091612", "日期": "20260916", "是否需要社区": "0", "__source_row_number": "2",
        "标题": "one\ntwo\nthree", "标题翻译": "一\n二\n三",
        "封面4：5": "标题1：x\n标题2：y\n标题3：z",
        "封面16：9": "标题1：x\n标题2：y\n标题3：z",
        "说明": "description", "说明翻译": "说明", "播放列表": "",
    }
    for tenant_id in ("tenant-b", "tenant-a"):
        with _tenant_session(store, tenant_id) as session:
            result = feishu_sync._sync_rows(session, "operation_packages", [row], "sheet")
            assert result["rows_inserted"] == 1
    with Session(store) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(WorkOrder)) == 2
        assert session.scalar(sa.select(sa.func.count()).select_from(OperationPackage)) == 2
        packages = session.scalars(sa.select(OperationPackage).order_by(OperationPackage.tenant_id)).all()
        assert [item.tenant_id for item in packages] == ["tenant-a", "tenant-b"]


def test_demo_batch_status_is_isolated_for_the_same_batch_code(store):
    with Session(store) as session:
        session.add_all([
            DemoDataBatch(
                tenant_id="tenant-a", batch_code=demo.BATCH_CODE, source_label="A", row_count=1,
                start_date=date(2026, 9, 1), end_date=date(2026, 9, 1), status="active",
            ),
            DemoDataBatch(
                tenant_id="tenant-b", batch_code=demo.BATCH_CODE, source_label="B", row_count=2,
                start_date=date(2026, 9, 2), end_date=date(2026, 9, 2), status="active",
            ),
        ])
        session.commit()
    with _tenant_session(store, "tenant-a") as session:
        status = demo.demo_status(session)
        assert status["active"] is True
        assert status["batch"].tenant_id == "tenant-a"
        assert status["batch"].row_count == 1


def _demo_payload() -> DemoDataImportRequest:
    return DemoDataImportRequest(
        work_rows=[{
            "剧名": "共享演示剧目", "地址": "https://www.youtube.com/watch/DEMO-SOURCE-001",
            "档期": "2026091712", "是否需要社区": "0",
        }],
        task_rows=[{
            "剧id": "DEMO-SOURCE-001", "档期": "2026091712", "日期": "20260917",
            "频道": "共享演示频道", "频道昵称": "英语共享演示频道", "播放列表": "演示播放列表",
            "标题": "title one\ntitle two\ntitle three", "标题翻译": "标题一\n标题二\n标题三",
            "封面4：5": "标题1：A\n副标题\n核心词：one\n标题2：B\n副标题\n核心词：two\n标题3：C\n副标题\n核心词：three",
            "封面16：9": "标题1：A\n副标题\n核心词：one\n标题2：B\n副标题\n核心词：two\n标题3：C\n副标题\n核心词：three",
            "说明": "demo description", "说明翻译": "演示说明",
            "剧目地址": "https://youtu.be/DEMO-SOURCE-001",
        }],
    )


def test_same_demo_import_is_idempotent_per_tenant_and_coexists_across_tenants(store):
    expected_counts = {
        "channel": 1, "drama": 1, "package": 1, "playlist": 1, "publish_slot": 1,
        "schedule": 1, "task": 1, "work_order": 1, "youtube_video": 1,
    }
    graph_models = (
        Channel, Drama, ChannelScheduleEntry, OperationTask, WorkOrder, OperationPackage, YoutubeVideo,
    )
    tenant_graphs = {}

    for tenant_id in ("tenant-a", "tenant-b"):
        with _tenant_session(store, tenant_id) as session:
            first = demo.import_feishu_demo(session, _demo_payload())
            repeated = demo.import_feishu_demo(session, _demo_payload())
            assert first["batch"].id == repeated["batch"].id
            assert first["entity_counts"] == expected_counts
            assert repeated["entity_counts"] == expected_counts
            tenant_graphs[tenant_id] = {
                model: tuple(session.scalars(sa.select(model)).all()) for model in graph_models
            }
            assert all(len(rows) == 1 for rows in tenant_graphs[tenant_id].values())
            assert all(rows[0].tenant_id == tenant_id for rows in tenant_graphs[tenant_id].values())

    for model in graph_models:
        assert tenant_graphs["tenant-a"][model][0].id != tenant_graphs["tenant-b"][model][0].id
    assert tenant_graphs["tenant-a"][Channel][0].youtube_channel_id != tenant_graphs["tenant-b"][Channel][0].youtube_channel_id
    assert tenant_graphs["tenant-a"][Drama][0].drama_code != tenant_graphs["tenant-b"][Drama][0].drama_code
    assert tenant_graphs["tenant-a"][YoutubeVideo][0].youtube_video_id != tenant_graphs["tenant-b"][YoutubeVideo][0].youtube_video_id
    assert ("youtube_channel_id",) in _unique_columns(Channel)
    assert ("drama_code",) in _unique_columns(Drama)
    assert ("idempotency_key",) in _unique_columns(ChannelScheduleEntry)
    assert ("youtube_video_id",) in _unique_columns(YoutubeVideo)


@pytest.mark.parametrize("info", [{}, {"tenant_id": "tenant-a"}])
def test_external_sync_services_reject_unscoped_sessions(store, info):
    empty_client = type("Client", (), {"iter_progress_items": lambda self, **kwargs: iter(())})()
    with Session(store, info=info) as session:
        with pytest.raises(HTTPException, match="主账号"):
            integration.list_integration_accounts(session, "feishu")
        with pytest.raises(HTTPException, match="主账号"):
            demo.demo_status(session)
        with pytest.raises(HTTPException, match="主账号"):
            feishu_sync._sync_rows(session, "work_orders", [], "sheet")
        with pytest.raises(HTTPException, match="主账号"):
            sync_zhihe_progress(session, empty_client)


def test_integration_and_sync_routes_bind_platform_and_tenant_sessions():
    integration_routes = {route.name: route for route in integration_api.router.routes}
    assert {dependency.call for dependency in integration_routes["get_integrations"].dependant.dependencies} == {
        auth_context.get_current_principal, database.get_db,
    }
    assert database.get_db in {
        dependency.call for dependency in integration_routes["post_integration"].dependant.dependencies
    }
    from zhiju.permissions import require_platform_permission
    assert require_platform_permission in {
        dependency.call for dependency in integration_routes["post_integration"].dependant.dependencies
    }
    for name, route in integration_routes.items():
        if name in {"get_integrations", "post_integration"}:
            continue
        assert auth_context.get_tenant_db in {dependency.call for dependency in route.dependant.dependencies}, name
    for router in (feishu_api.router, demo_api.router):
        for route in router.routes:
            assert auth_context.get_tenant_db in {
                dependency.call for dependency in route.dependant.dependencies
            }, route.name
