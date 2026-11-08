"""One tenant-wide admission limit and FIFO queue for all Codex task types."""
from datetime import datetime,timezone
from sqlalchemy import select,func,literal,union_all
from zhiju.models import ChannelAnalysisRun,ChannelSchedulePlan,ExecutorClaim
from zhiju.models.v14 import V14Run,V14Setting
from zhiju.services.identity import ConflictError

WORKER_LIMIT=10
MODELS={'operation_package':V14Run,'channel_analysis':ChannelAnalysisRun,'channel_scheduling':ChannelSchedulePlan}


def counts(session):
    stats={'running':0,'queued':0,'worker_limit':WORKER_LIMIT,'types':{}}
    claims=list(session.execute(select(ExecutorClaim.task_type,ExecutorClaim.run_id,ExecutorClaim.released_at)).all())
    held={(kind,run) for kind,run,released in claims if released is None}
    known={(kind,run) for kind,run,released in claims}
    for kind,model in MODELS.items():
        running=set(session.scalars(select(model.id).where(model.status=='running')))
        reserved={run for task,run in held if task==kind}
        queued=session.scalar(select(func.count()).select_from(model).where(model.status=='queued'))
        stats['types'][kind]={'running':len((running-{run for task,run in known if task==kind})|reserved),'queued':queued}
        stats['running']+=stats['types'][kind]['running'];stats['queued']+=queued
    return stats


def reserve(session,kind,run):
    session.add(ExecutorClaim(task_type=kind,run_id=run.id,host_id=run.host_id,claim_id=run.claim_id))


def release(session,host_id,claim_id,commit=True):
    row=session.scalar(select(ExecutorClaim).where(ExecutorClaim.claim_id==claim_id,ExecutorClaim.host_id==host_id).with_for_update())
    if row and row.released_at is None:row.released_at=datetime.now(timezone.utc)
    if commit:session.commit()
    return {'released':True}


def release_stopped_run(session,kind,run_id):
    # The caller has explicitly confirmed the previous execution stopped; cancel
    # may already have cleared the business row's claim_id.
    for row in session.scalars(select(ExecutorClaim).where(ExecutorClaim.task_type==kind,
            ExecutorClaim.run_id==run_id,ExecutorClaim.released_at.is_(None)).with_for_update()):
        row.released_at=datetime.now(timezone.utc)


def admission(session):
    # Every claim path takes this same lock before counting or reserving a job.
    setting=session.scalar(select(V14Setting).with_for_update())
    if not setting:raise ConflictError('请先配置 Codex 执行主机')
    return counts(session)['running']<WORKER_LIMIT


def claim_next(session,host_id,claim_id,executor_protocol):
    if not claim_id:raise ConflictError('统一领取需要请求ID')
    available=admission(session)
    from zhiju.services import v14_runs,channel_analysis,schedule_planning
    for kind,model in MODELS.items():
        old=session.scalar(select(model).where(model.host_id==host_id,model.claim_id==claim_id,model.status=='running'))
        if old:
            run=v14_runs.claim_read(session,old) if kind=='operation_package' else {**(channel_analysis.run_read(old) if kind=='channel_analysis' else schedule_planning.read(old)),'tenant_id':old.tenant_id}
            return {'task_type':kind,'run':run}
    def queued_for_host(model, query):
        query = query.where(model.host_id==host_id, model.status=='queued')
        return schedule_planning.claimable_plans(query, executor_protocol) if model is ChannelSchedulePlan else query

    own_queued=sum(session.scalar(queued_for_host(m, select(func.count()).select_from(m))) for m in MODELS.values())
    if not own_queued:return None
    if not available:return {'waiting_for_capacity':True,'worker_limit':WORKER_LIMIT}
    from sqlalchemy.orm import aliased
    other=aliased(ChannelAnalysisRun)
    busy=select(other.id).where(other.channel_id==ChannelAnalysisRun.channel_id,other.tenant_id==ChannelAnalysisRun.tenant_id,other.status=='running').exists()
    queries=[]
    for kind,m in MODELS.items():
        q=queued_for_host(m, select(m.id,m.updated_at.label('queued_at'),literal(kind).label('task_type')))
        if kind=='channel_analysis':q=q.where(~busy)
        queries.append(q)
    queue=union_all(*queries).subquery()
    selected=session.execute(select(queue.c.id,queue.c.task_type).order_by(queue.c.queued_at,queue.c.id).limit(1)).first()
    if selected is None:return {'waiting_for_capacity':True,'worker_limit':WORKER_LIMIT}
    id,kind=selected
    if kind=='operation_package':
        run=v14_runs.claim_run(session,host_id,executor_protocol=executor_protocol,claim_id=claim_id,run_id=id)
    elif kind=='channel_analysis':run=channel_analysis.claim_run(session,host_id,claim_id=claim_id,run_id=id)
    else:run=schedule_planning.claim_plan(session,host_id,claim_id=claim_id,plan_id=id,executor_protocol=executor_protocol)
    return {'task_type':kind,'run':run} if run else {'waiting_for_capacity':True,'worker_limit':WORKER_LIMIT}
