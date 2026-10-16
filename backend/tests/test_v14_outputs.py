import pytest
import sqlalchemy as sa

from test_v14_runs import store, configure
from zhiju.database import TenantSession
from zhiju.models.v14 import V14Attempt


def test_search_rejects_unverified_replacement_plot(store):
    from zhiju.services.v14_outputs import apply_outputs
    from zhiju.services.v14_runs import create_run
    from zhiju.services.identity import ConflictError
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        configure(s)
        run = create_run(s, "work-a")
        attempt = V14Attempt(run_id=run.id, claim_id="claim", node_type="search", sequence=1)
        with pytest.raises(ConflictError):
            apply_outputs(s, run, attempt, {"plot_payload": {"results": [{"plot_fields": {"内容概述": "伪造剧情"}}]}})


def test_title_writer_without_commit_can_be_rolled_back(store):
    from zhiju.models import ProductionNodeRun, PackageTitle
    from zhiju.services.package_outputs import write_titles
    from zhiju.schemas.production import TitleBatchWrite
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        node = s.scalar(sa.select(ProductionNodeRun).where(ProductionNodeRun.node_type == "title"))
        node.status = "running"
        s.commit()
        write_titles(s, "package-a", TitleBatchWrite(titles=[{"variant_number": n, "localized_title": f"新标题{n}"} for n in (1, 2, 3)]), commit=False)
        s.rollback()
        assert s.scalar(sa.select(sa.func.count()).select_from(PackageTitle)) == 0


def test_search_acceptance_preserves_raw_json_and_advances_once(store):
    from copy import deepcopy
    from test_v14_contract import envelope as example
    from v14_fixtures import valid_market_payload
    from zhiju.services import v14_runs as runs
    from zhiju.schemas.v14 import AttemptSubmission
    from zhiju.models import ProductionNodeRun
    from zhiju.v14_runtime.contract import build_stage_input
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        setting = configure(s)
        config = deepcopy(setting.payload)
        sample = example()
        config["rules"] = sample["rules_snapshot"]
        config["channel_inputs"]["channel-a"] = sample["input_snapshot"]["channel"]
        runs.save_settings(s, config)
        run = runs.create_run(s, "work-a")
        claim = runs.claim_run(s, "device-a")
        stage = build_stage_input(claim, "search")
        market = valid_market_payload()
        market.update(drama_id="2026-10-20", drama_title="剧目", selection_context={"channel_name": "频道", "channel_language": "阿拉伯语", "channel_type": "复仇"})
        payload = {"plot_payload": stage.context["plot_payload"], "market_payload": market,
                   "external_evidence": {"status": "completed", "videos": [{"video_url": "https://www.youtube.com/watch?v=abcdefghijk"}]}}
        attempt = runs.begin_attempt(s, run.id, claim["claim_id"], "search")
        submission = AttemptSubmission(claim_id=claim["claim_id"], outcome="accepted", result=payload)
        first = runs.submit_attempt(s, run.id, attempt.id, submission)
        assert runs.submit_attempt(s, run.id, attempt.id, submission) == first
        assert attempt.raw_payload == payload
        assert attempt.payload["external_evidence"]["videos"][0]["video_url"] == "https://www.youtube.com/watch?v=abcdefghijk"
        nodes = {n.node_type: n.status for n in s.scalars(sa.select(ProductionNodeRun))}
        assert nodes["search"] == "completed" and nodes["title"] == "queued"
