import pytest
from test_channel_analysis_runs import session
from zhiju.services import channel_analysis as service
from zhiju.services.identity import ConflictError


def failed(s,c):
    run=service.create_run(s,c.id,mode='initial',positioning='old')
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    service.submit_result(s,run.id,claim['claim_id'],error='model timeout')
    return run


def test_old_failure_cannot_resume_over_new_active_task(session):
    s,c=session;old=failed(s,c)
    new=service.create_run(s,c.id,mode='initial',positioning='new');service.start_run(s,new.id)
    with pytest.raises(ConflictError,match='未结束'):service.resume_run(s,old.id,True)
    assert old.status=='failed' and new.status=='queued'
    assert service.claim_run(s,'host')['id']==new.id
    assert service.claim_run(s,'host') is None


def test_existing_duplicate_queue_cannot_run_same_channel_together(session):
    s,c=session;old=failed(s,c)
    new=service.create_run(s,c.id,mode='initial',positioning='new');service.start_run(s,new.id)
    # Historical duplicate queued rows are possible from the previous resume endpoint.
    old.status='queued';s.commit()
    first=service.claim_run(s,'host');assert first
    assert service.claim_run(s,'host') is None
    service.submit_result(s,first['id'],first['claim_id'],error='failure releases this channel')
    second=service.claim_run(s,'host')
    assert second and second['id']!=first['id'] and second['channel_id']==first['channel_id']
