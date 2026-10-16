from datetime import date

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from zhiju.database import TenantSession
from zhiju.models import Base, Channel, Drama, OperationPackage, PackageTitle, WorkOrder


@pytest.fixture
def store():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for number, key in enumerate(("a", "b"), 1):
            s.add_all([
                Channel(id=f"channel-{key}", tenant_id=f"tenant-{key}", youtube_channel_id=f"UC-{key}", original_name="频道", status="active"),
                Drama(id=f"drama-{key}", tenant_id=f"tenant-{key}", drama_number=number, drama_code=f"DR-{key}", chinese_title="剧目", normalized_title="剧目", content_summary="真剧情", plot_archive="档案", plot_pattern="套路", core_personas="人设"),
                WorkOrder(id=f"work-{key}", tenant_id=f"tenant-{key}", task_id=f"task-{key}", batch_id=f"batch-{key}", channel_id=f"channel-{key}", drama_id=f"drama-{key}", production_date=date(2026, 10, 17), target_publish_date=date(2026, 10, 20), community_count=1),
                OperationPackage(id=f"package-{key}", tenant_id=f"tenant-{key}", work_order_id=f"work-{key}", channel_id=f"channel-{key}", drama_id=f"drama-{key}", status="building"),
            ])
        s.commit()
    yield engine
    engine.dispose()


def configure(s):
    from zhiju.services.v14_runs import save_settings
    return save_settings(s, {
        "host_id": "device-a", "account_profile": "current", "default_model": "test-model",
        "available_models": ["test-model"], "rules": {"version": "V14", "title": {"rule": "original"}},
        "channel_inputs": {"channel-a": {"generation_spec": "[GLOBAL]\n规则\n[TITLE]\n标题", "language": "ar"}},
    })


def test_create_run_freezes_inputs(store):
    from zhiju.services.v14_runs import create_run, save_settings
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        config = configure(s)
        run = create_run(s, "work-a")
        run_id = run.id
        changed = dict(config.payload)
        changed["default_model"] = "another-model"
        save_settings(s, changed)
        s.expire_all()
        assert run.model == "test-model"
        assert run.input_snapshot["drama"]["content_summary"] == "真剧情"
        assert run.rules_snapshot["title"]["rule"] == "original"
        assert create_run(s, "work-a").id == run_id


def test_existing_imported_outputs_are_not_overwritten(store):
    from zhiju.services.v14_runs import create_run
    from zhiju.services.identity import ConflictError
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        configure(s)
        s.add(PackageTitle(package_id="package-a", variant_number=1, localized_title="旧飞书结果", selected=True, status="selected"))
        s.commit()
        with pytest.raises(ConflictError, match="已有"):
            create_run(s, "work-a")
        assert s.scalar(sa.select(PackageTitle)).localized_title == "旧飞书结果"


def test_tenant_cannot_read_other_run(store):
    from zhiju.services.v14_runs import create_run, get_run
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        configure(s)
        run_id = create_run(s, "work-a").id
    with TenantSession(store, info={"tenant_id": "tenant-b"}) as s:
        with pytest.raises(HTTPException) as exc:
            get_run(s, run_id)
        assert exc.value.status_code == 404


def test_migration_creates_only_v14_tables():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "alembic/versions/7b14a201d001_add_v14_execution.py"
    assert path.exists(), "V14 migration missing"
    spec = importlib.util.spec_from_file_location("v14_migration", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE unrelated (id INTEGER)")
        revision.op = Operations(MigrationContext.configure(conn))
        revision.upgrade()
        assert set(sa.inspect(conn).get_table_names()) == {"unrelated", "v14_settings", "v14_runs", "v14_attempts"}
        revision.downgrade()
        assert sa.inspect(conn).get_table_names() == ["unrelated"]
