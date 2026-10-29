import pytest
import sqlalchemy as sa
from test_v14_runs import store, configure
from zhiju.database import TenantSession
from zhiju.models import ProductionNodeRun
from zhiju.models.v14 import V14Attempt
from zhiju.services import v14_runs as runs
from zhiju.services.identity import ConflictError
from zhiju.schemas.v14 import AttemptSubmission


def test_manual_retry_retains_accepted_stage_and_history_and_limits_new_round_to_three(store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        configure(s);run=runs.create_run(s,'work-a')
        run.status='needs_user_review';run.error='title_1_invalid_hook_b_type';run.claim_id='old'
        accepted=V14Attempt(tenant_id='tenant-a',run_id=run.id,claim_id='old',node_type='search',sequence=1,outcome='accepted',payload={'kept':True})
        s.add(accepted)
        for i in range(1,4):
            s.add(V14Attempt(tenant_id='tenant-a',run_id=run.id,claim_id='old',node_type='title',sequence=i,outcome='content_error',error='invalid hook'))
        node=s.scalar(sa.select(ProductionNodeRun).where(ProductionNodeRun.work_order_id=='work-a',ProductionNodeRun.node_type=='title'))
        node.status='running';node.worker_key='device-a';s.commit()
        with pytest.raises(ConflictError):runs.resume_run(s,run.id,True)
        with pytest.raises(ConflictError):runs.resume_run(s,run.id,False,retry_content=True)
        assert runs.resume_run(s,run.id,True,retry_content=True)['status']=='queued'
        claim=runs.claim_run(s,'device-a')
        assert claim['accepted_results']['search']=={'kept':True}
        for i in range(4,7):
            attempt=runs.begin_attempt(s,run.id,claim['claim_id'],'title')
            assert attempt.sequence==i
            result=runs.submit_attempt(s,run.id,attempt.id,AttemptSubmission(claim_id=claim['claim_id'],outcome='content_error',result={},error='still invalid'))
            assert result['status']==('needs_user_review' if i==6 else 'running')
        assert len(runs.attempts(s,run))==7
        assert accepted.payload=={'kept':True} and accepted.outcome=='accepted'


def test_manual_retry_cannot_restart_completed_run(store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        configure(s);run=runs.create_run(s,'work-a');run.status='text_ready';s.commit()
        with pytest.raises(ConflictError):runs.resume_run(s,run.id,True,retry_content=True)
