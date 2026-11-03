from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, Response
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


class Claim(BaseModel):
    host_id: str


class Execution(BaseModel):
    claim_id: str
    result: dict | None = None
    error: str | None = None


class Resume(BaseModel):
    stopped_confirmed: bool = False


@router.get('/channels/{channel_id}/schedule-plans')
def listing(channel_id:str,s:Session=Depends(get_tenant_db)):
    return [service.read(r,summary=True) for r in service.list_plans(s,channel_id)]


@router.post('/channels/{channel_id}/schedule-plans')
def create(channel_id:str,body:PlanCreate,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.read(call(service.create_plan,s,channel_id,body.start_date,body.end_date,body.daily_count))


@router.get('/schedule-plans/{plan_id}')
def read(plan_id:str,s:Session=Depends(get_tenant_db)):
    return service.read(service.get_plan(s,plan_id))


@router.post('/schedule-planning/claims')
def claim(body:Claim,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    bound_host(s,p,body.host_id)
    result=call(service.claim_plan,s,body.host_id)
    return result if result else Response(status_code=204)


@router.post('/schedule-plans/{plan_id}/heartbeat')
def heartbeat(plan_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=call(service.claimed,s,plan_id,body.claim_id);bound_host(s,p,row.host_id)
    row.heartbeat_at=datetime.now(timezone.utc);s.commit();return {'status':row.status}


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
