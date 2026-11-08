from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Response, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from zhiju.auth_context import get_tenant_db
from zhiju.api.v14 import operator, bound_host, call
from zhiju.services import schedule_planning as service

router=APIRouter(prefix='/v3',tags=['channel-scheduling'])


class PlanCreate(BaseModel):
    start_date: date
    end_date: date
    daily_count: int = Field(ge=1,le=10)
    executor_protocol: int | None = None
    slot_topics: dict[str, Literal["primary", "secondary"]] | None = None


class Claim(BaseModel):
    host_id: str
    executor_protocol: int = 1


class Execution(BaseModel):
    claim_id: str
    result: dict | None = None
    error: str | None = None
    progress: dict | None = None


class Resume(BaseModel):
    stopped_confirmed: bool = False


@router.get('/schedule-planning/workspace')
def workspace(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),
              status:Literal['active','all','queued','running','failed','ready','applied','cancelled']='active',
              search:str='',s:Session=Depends(get_tenant_db)):
    return service.workspace(s,page,page_size,status,search)


@router.get('/channels/{channel_id}/schedule-plans')
def listing(channel_id:str,s:Session=Depends(get_tenant_db)):
    return [service.read(r,summary=True) for r in service.list_plans(s,channel_id)]


@router.post('/channels/{channel_id}/schedule-plans')
def create(channel_id:str,body:PlanCreate,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.read(call(service.create_plan,s,channel_id,body.start_date,body.end_date,body.daily_count,body.slot_topics,executor_protocol=body.executor_protocol))


@router.get('/schedule-plans/{plan_id}')
def read(plan_id:str,s:Session=Depends(get_tenant_db)):
    return service.read(service.get_plan(s,plan_id))


@router.post('/schedule-planning/claims')
def claim(body:Claim,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    bound_host(s,p,body.host_id)
    from zhiju.api.v14 import require_shared_queue_protocol
    require_shared_queue_protocol(body.executor_protocol)
    result=call(service.claim_plan,s,body.host_id,executor_protocol=body.executor_protocol)
    return result if result else Response(status_code=204)


@router.post('/schedule-plans/{plan_id}/heartbeat')
def heartbeat(plan_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=call(service.claimed,s,plan_id,body.claim_id);bound_host(s,p,row.host_id)
    row.heartbeat_at=datetime.now(timezone.utc)
    if body.progress is not None:row.progress=body.progress
    s.commit();return {'status':row.status}


@router.put('/schedule-plans/{plan_id}/result')
def submit(plan_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=service.get_plan(s,plan_id);bound_host(s,p,row.host_id)
    return service.read(call(service.submit_result,s,plan_id,body.claim_id,result=body.result,error=body.error))


@router.post('/schedule-plans/{plan_id}/apply')
def apply(plan_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.read(call(service.apply_plan,s,plan_id))


@router.post('/schedule-plans/{plan_id}/cancel')
def cancel(plan_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.read(call(service.cancel_plan,s,plan_id))


@router.post('/schedule-plans/{plan_id}/resume')
def resume(plan_id:str,body:Resume,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.read(call(service.resume_plan,s,plan_id,body.stopped_confirmed))
