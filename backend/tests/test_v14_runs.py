from datetime import date

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from zhiju.database import TenantSession
from zhiju.models import Base, Channel, Drama, OperationPackage, PackageTitle, WorkOrder, OperationTask, ProductionBatch, ProductionNodeRun


@pytest.fixture
def store():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for number, key in enumerate(("a", "b"), 1):
            s.add_all([
                ProductionBatch(id=f"batch-{key}", tenant_id=f"tenant-{key}", batch_number=f"batch-{key}", production_date=date(2026, 10, 17), source="native"),
                OperationTask(id=f"task-{key}", tenant_id=f"tenant-{key}", batch_id=f"batch-{key}", channel_id=f"channel-{key}", drama_id=f"drama-{key}", source="manual", task_date=date(2026, 10, 17), target_publish_date=date(2026, 10, 20), idempotency_key=f"task-{key}", status="dispatched", community_count=1),
                Channel(id=f"channel-{key}", tenant_id=f"tenant-{key}", youtube_channel_id=f"UC-{key}", original_name="频道", status="active"),
                Drama(id=f"drama-{key}", tenant_id=f"tenant-{key}", drama_number=number, drama_code=f"DR-{key}", chinese_title="剧目", normalized_title="剧目", content_summary="真剧情", plot_archive="档案", plot_pattern="套路", core_personas="人设"),
                WorkOrder(id=f"work-{key}", tenant_id=f"tenant-{key}", task_id=f"task-{key}", batch_id=f"batch-{key}", channel_id=f"channel-{key}", drama_id=f"drama-{key}", production_date=date(2026, 10, 17), target_publish_date=date(2026, 10, 20), community_count=1),
                OperationPackage(id=f"package-{key}", tenant_id=f"tenant-{key}", work_order_id=f"work-{key}", channel_id=f"channel-{key}", drama_id=f"drama-{key}", status="building"),
            ])
            for i, node in enumerate(("search", "title", "cover", "description", "community", "merge"), 1):
                s.add(ProductionNodeRun(tenant_id=f"tenant-{key}", work_order_id=f"work-{key}", package_id=f"package-{key}", node_type=node, sequence_number=i, attempt_number=1, idempotency_key=f"{node}-{key}", status="queued" if i == 1 else "pending"))
        s.commit()
    yield engine
    engine.dispose()


def configure(s):
    from zhiju.services.v14_runs import save_settings
    from test_v14_contract import envelope
    sample = envelope()
    sample["rules_snapshot"]["title"] = {"rule": "original"}
    return save_settings(s, {
        "host_id": "device-a", "account_profile": "current", "default_model": "test-model",
        "available_models": ["test-model"], "rules": sample["rules_snapshot"],
        "channel_inputs": {"channel-a": sample["input_snapshot"]["channel"]},
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
        assert run.rules_snapshot['skill_bundle']['label'] == 'V14'
        assert run.rules_snapshot['skill_bundle']['archive']
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


def test_incomplete_channel_configuration_blocks_start(store):
    from copy import deepcopy
    from zhiju.services.v14_runs import create_run, save_settings
    from zhiju.services.identity import ConflictError
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        config = deepcopy(configure(s).payload)
        config["channel_inputs"]["channel-a"]["generation_spec"] = ""
        save_settings(s, config)
        with pytest.raises(ConflictError, match="generation_spec"):
            create_run(s, "work-a")


@pytest.mark.parametrize("field,value,want", [
    ("description_fixed_assets", {"disclaimer": "声明"}, "subscribe_line"),
    ("playlists", [], "playlist"),
    ("channel_hashtag_whitelist", {}, "hashtag"),
    ("community_footer_cta", {"text": "关注"}, "full_video_cta"),
])
def test_static_material_faults_block_snapshot_before_any_model(store, field, value, want):
    from copy import deepcopy
    from zhiju.services.v14_runs import create_run, save_settings
    from zhiju.services.identity import ConflictError
    from zhiju.models.v14 import V14Run, V14Attempt
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        config = deepcopy(configure(s).payload)
        config["channel_inputs"]["channel-a"][field] = value
        save_settings(s, config)
        with pytest.raises(ConflictError, match=want):
            create_run(s, "work-a")
        assert s.scalar(sa.select(sa.func.count()).select_from(V14Run)) == 0
        assert s.scalar(sa.select(sa.func.count()).select_from(V14Attempt)) == 0


def test_channel_material_language_must_match_channel(store):
    from copy import deepcopy
    from zhiju.services.v14_runs import create_run, save_settings
    from zhiju.services.identity import ConflictError
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        config = deepcopy(configure(s).payload)
        s.get(Channel, "channel-a").default_language = "ar"
        config["channel_inputs"]["channel-a"]["language"] = "英语"
        save_settings(s, config)
        with pytest.raises(ConflictError, match="语言"):
            create_run(s, "work-a")


def test_configured_channel_uses_existing_production_eligibility(store):
    from zhiju.services.v14_runs import create_run
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        configure(s)
        s.get(Channel, "channel-a").status = "configured"
        s.commit()
        assert create_run(s, "work-a").status == "queued"


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


def test_mysql_v14_ddl_has_distinct_unique_index_names():
    import importlib.util
    import io
    import re
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from zhiju.models.base import NAMING_CONVENTION
    from zhiju.models.v14 import V14Run

    names = [c.name for c in V14Run.__table__.constraints if isinstance(c, sa.UniqueConstraint)]
    assert len(names) == len(set(names)), "MySQL rejects duplicate unique index names"
    path = Path(__file__).parents[1] / "alembic/versions/7b14a201d001_add_v14_execution.py"
    spec = importlib.util.spec_from_file_location("v14_mysql_migration", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={
        "as_sql": True, "output_buffer": output,
        "target_metadata": sa.MetaData(naming_convention=NAMING_CONVENTION),
    })
    revision.op = Operations(context)
    revision.upgrade()
    for statement in output.getvalue().split(";"):
        names = re.findall(r"CONSTRAINT (\w+) UNIQUE", statement)
        assert len(names) == len(set(names)), statement


def test_begin_attempt_marks_node_running_before_result_and_keeps_start_on_content_retry(store):
    from zhiju.services import v14_runs as runs
    from zhiju.schemas.v14 import AttemptSubmission
    with TenantSession(store, info={'tenant_id':'tenant-a'}) as s:
        configure(s)
        run=runs.create_run(s,'work-a')
        claim=runs.claim_run(s,'device-a')
        attempt=runs.begin_attempt(s,run.id,claim['claim_id'],'search')
        node=s.scalar(sa.select(ProductionNodeRun).where(ProductionNodeRun.node_type=='search'))
        assert node.status=='running' and node.worker_key=='device-a'
        assert node.started_at is not None and node.completed_at is None
        assert s.get(WorkOrder,'work-a').status=='running'
        started=node.started_at
        runs.submit_attempt(s,run.id,attempt.id,AttemptSubmission(
            claim_id=claim['claim_id'],outcome='content_error',result={},error='invalid result'))
        runs.begin_attempt(s,run.id,claim['claim_id'],'search')
        assert node.started_at==started
        assert node.completed_at is None
