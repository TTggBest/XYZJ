from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, UploadFile, File, Form, Response, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from zhiju.auth_context import get_tenant_db
from zhiju.api.v14 import operator, bound_host, call
from zhiju.services import channel_analysis as service
from zhiju.services.channel_analysis_sources import collect

router=APIRouter(prefix='/v3',tags=['channel-analysis'])


class AnalysisCreate(BaseModel):
    mode: Literal['initial','periodic']
    positioning: str = ''
    posts_not_applicable: bool = False
    ab_not_applicable: bool = False


class Claim(BaseModel):
    host_id: str


class Execution(BaseModel):
    claim_id: str
    result: dict | None = None
    error: str | None = None
    paths: dict[str,str] | None = None
    initial_context: dict | None = None
    progress: dict | None = None


class Resume(BaseModel):
    stopped_confirmed: bool = False


@router.get('/channels/{channel_id}/analysis-runs')
def listing(channel_id:str,s:Session=Depends(get_tenant_db)):
    return service.list_run_summaries(s,channel_id)


@router.get('/channels/{channel_id}/analysis-history')
def history(channel_id:str,page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=50),s:Session=Depends(get_tenant_db)):
    return service.analysis_history(s,channel_id,page,page_size)


@router.get('/channel-analysis/workspace')
def workspace(view:Literal['results','progress']='results',page:int=Query(1,ge=1),
              page_size:int=Query(20,ge=1,le=50),search:str='',s:Session=Depends(get_tenant_db)):
    return service.analysis_workspace(s,view,page,page_size,search)


@router.post('/channels/{channel_id}/analysis-runs')
def create(channel_id:str,body:AnalysisCreate,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.run_read(call(service.create_run,s,channel_id,**body.model_dump()))


@router.get('/analysis-runs/{run_id}')
def read(run_id:str,s:Session=Depends(get_tenant_db)):
    return service.run_read(service.get_run(s,run_id))


@router.post('/analysis-runs/{run_id}/materials')
async def upload(run_id:str,kind:str=Form(...),file:UploadFile=File(...),s:Session=Depends(get_tenant_db),p=Depends(operator)):
    content=await file.read(32*1024*1024+1)
    return service.run_read(call(service.add_material,s,run_id,kind,file.filename or 'material',content))


@router.get('/analysis-runs/{run_id}/materials/{material_id}')
def download(run_id:str,material_id:str,s:Session=Depends(get_tenant_db)):
    run=service.get_run(s,run_id)
    path=call(service.material_path,run,material_id)
    return FileResponse(path)


@router.post('/analysis-runs/{run_id}/start')
def start(run_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.run_read(call(service.start_run,s,run_id))


@router.post('/analysis-runs/{run_id}/screenshot-checks')
def screenshot_checks(run_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    checked(s,p,run_id,body.claim_id)
    row=call(service.record_screenshot_checks,s,run_id,body.claim_id,body.result or {})
    s.refresh(row)  # Return the persisted JSON number representation used by final validation.
    return service.run_read(row)


@router.delete('/analysis-runs/{run_id}')
def delete(run_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=call(service.delete_run,s,run_id)
    return {'id':row.id,'status':row.status}


@router.post('/analysis-runs/{run_id}/cancel')
def cancel(run_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.run_read(call(service.cancel_run,s,run_id))


@router.post('/analysis-runs/{run_id}/resume')
def resume(run_id:str,body:Resume,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.run_read(call(service.resume_run,s,run_id,body.stopped_confirmed))


@router.post('/analysis-runs/{run_id}/apply')
def apply(run_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=call(service.apply_result,s,run_id)
    return {key:getattr(row,key) for key in ('id','channel_id','status','report_id','dna_id','mirror_status')}


@router.post('/channel-analysis/claims')
def claim(body:Claim,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    bound_host(s,p,body.host_id)
    row=call(service.claim_run,s,body.host_id)
    return row if row else Response(status_code=204)


def checked(s,p,run_id,claim_id):
    row=call(service.claimed,s,run_id,claim_id)
    bound_host(s,p,row.host_id)
    return row


@router.post('/analysis-runs/{run_id}/collect')
def gather(run_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    run=checked(s,p,run_id,body.claim_id)
    if run.mode=='periodic' and body.initial_context:
        snapshot=dict(run.input_snapshot)
        snapshot['local_analysis_context']=body.initial_context
        run.input_snapshot=snapshot;s.commit()
    if run.input_snapshot.get('cold_start') and body.initial_context:
        snapshot=dict(run.input_snapshot);context=body.initial_context
        channel=dict(snapshot['channel'])
        for key in ('default_language','country_name_zh'):
            if not channel.get(key):channel[key]=context.get('channel',{}).get(key)
        if not channel.get('default_language') or not channel.get('country_name_zh'):
            from fastapi import HTTPException
            raise HTTPException(409,'本机注册资料仍缺目标语言或市场，请补充后重建冷启动任务')
        snapshot['channel']=channel
        snapshot['local_initial_context']=context
        run.input_snapshot=snapshot;s.commit()
    row=call(collect,s,run_id,body.claim_id)
    s.refresh(row)  # MySQL JSON may normalize the last digit of computed floats.
    return service.run_read(row)


@router.post('/analysis-runs/{run_id}/heartbeat')
def heartbeat(run_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=checked(s,p,run_id,body.claim_id);row.heartbeat_at=datetime.now(timezone.utc)
    if body.progress is not None:row.progress=body.progress
    s.commit();return {'status':row.status,'phase':row.phase}


@router.put('/analysis-runs/{run_id}/result')
def submit(run_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=service.get_run(s,run_id);bound_host(s,p,row.host_id)
    return service.run_read(call(service.submit_result,s,run_id,body.claim_id,result=body.result,error=body.error))


@router.post('/analysis-runs/{run_id}/mirror-complete')
def mirrored(run_id:str,body:Execution,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    row=service.get_run(s,run_id,True);bound_host(s,p,row.host_id)
    if row.claim_id!=body.claim_id or row.status not in {'ready','applied'}:
        from fastapi import HTTPException
        raise HTTPException(409,'镜像结果不属于当前领取')
    row.mirror_status='failed' if body.error else 'completed'
    if body.paths or body.error:
        row.result={**(row.result or {}),'delivery':{'paths':body.paths or {},'error':body.error}}
    s.commit();return {'status':row.mirror_status}


class ColdStartInput(BaseModel):
    chinese_meaning: str = ''
    positioning: str = ''
    language: str = ''
    market: str = ''

@router.post('/channels/{channel_id}/cold-start')
def cold_start(channel_id:str,body:ColdStartInput,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    run=call(service.create_run,s,channel_id,mode='initial',positioning=body.positioning,
             cold_start=True,initial_facts=body.model_dump())
    return service.run_read(call(service.start_run,s,run.id))
