from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal, get_current_principal, get_tenant_db
from zhiju.models import WorkOrder
from zhiju.models.v14 import V14Run
from zhiju.schemas.v14 import (V14SettingsWrite, ClaimRequest, AttemptStart, AttemptSubmission, ClaimIdentity, ResumeRequest)
from zhiju.services import v14_runs as service
from zhiju.services.identity import ConflictError
from zhiju.services.channel import NotFoundError
from zhiju.tenant_repository import require_tenant_entity
from zhiju.api.auth import require_same_origin
from zhiju.services.v14_sessions import authorize_executor

router = APIRouter(prefix="/v3", tags=["v14"])


class CommunityRequirement(BaseModel):
    community_count: int = Field(ge=0, le=20)


class ProductionVersion(BaseModel):
    workflow_version_id: str | None = None


@router.post("/v14/executor-session", dependencies=[Depends(require_same_origin)])
def executor_session(response: Response, s: Session = Depends(get_tenant_db), p=Depends(get_current_principal)):
    operator(p)
    result = call(authorize_executor, s, p)
    response.headers["Cache-Control"] = "no-store"
    return result


def operator(principal: Principal = Depends(get_current_principal)):
    if principal.platform_role != "super_admin" and principal.membership_role not in {"owner", "admin"}:
        raise HTTPException(403, "需要当前公司管理权限")
    return principal


@router.patch("/tasks/{entity_id}/community")
def task_community(entity_id: str, body: CommunityRequirement, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    from zhiju.services.community_requirements import update_community
    return call(update_community, s, "tasks", entity_id, body.community_count)


@router.patch("/schedules/{entity_id}/community")
def schedule_community(entity_id: str, body: CommunityRequirement, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    from zhiju.services.community_requirements import update_community
    return call(update_community, s, "schedules", entity_id, body.community_count)


def bound_host(session, principal, host_id):
    setting = service.get_settings(session)
    if principal.tenant_id != session.info["tenant_id"] or not principal.device_id or principal.device_id != host_id or not setting or setting.payload["host_id"] != host_id:
        raise HTTPException(403, "当前会话设备与公司绑定执行主机不一致")


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/v14/settings")
def read_settings(s: Session = Depends(get_tenant_db), p=Depends(operator)):
    row = service.get_settings(s)
    return row.payload if row else None


@router.put("/v14/settings")
def put_settings(body: V14SettingsWrite, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return service.save_settings(s, body.model_dump(exclude_unset=True)).payload


@router.post("/work-orders/{work_order_id}/v14-runs")
def create(work_order_id: str, body: ProductionVersion | None = None, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return service.run_read(s, call(service.create_run, s, work_order_id, workflow_version_id=body.workflow_version_id if body else None))


@router.post("/tasks/{task_id}/start-v14")
def start_task(task_id: str, body: ProductionVersion | None = None, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return service.run_read(s, call(service.start_task, s, task_id, workflow_version_id=body.workflow_version_id if body else None))


@router.get("/work-orders/{work_order_id}/v14-runs/current")
def current(work_order_id: str, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    require_tenant_entity(s, WorkOrder, work_order_id)
    run = s.scalar(select(V14Run).where(V14Run.work_order_id == work_order_id))
    return service.run_read(s, run) if run else None


@router.post("/v14/claims")
def claim(body: ClaimRequest, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    bound_host(s, p, body.host_id)
    result = call(service.claim_run, s, body.host_id, executor_protocol=body.executor_protocol)
    return result if result else Response(status_code=204)


def execution_run(s, p, run_id):
    run = service.get_run(s, run_id)
    bound_host(s, p, run.host_id)
    return run


@router.post("/v14/runs/{run_id}/attempts")
def begin(run_id: str, body: AttemptStart, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    execution_run(s, p, run_id)
    attempt = call(service.begin_attempt, s, run_id, body.claim_id, body.node_type)
    return {"attempt_id": attempt.id}


@router.put("/v14/runs/{run_id}/attempts/{attempt_id}")
def submit(run_id: str, attempt_id: str, body: AttemptSubmission, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    execution_run(s, p, run_id)
    return call(service.submit_attempt, s, run_id, attempt_id, body)


@router.post("/v14/runs/{run_id}/heartbeat")
def heartbeat(run_id: str, body: ClaimIdentity, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    run = execution_run(s, p, run_id)
    call(service.check_claim, run, body.claim_id)
    run.heartbeat_at = datetime.now(timezone.utc)
    s.commit()
    return service.run_read(s, run)


@router.post("/v14/runs/{run_id}/cancel")
def cancel(run_id: str, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return call(service.cancel_run, s, run_id)


@router.post("/v14/runs/{run_id}/resume")
def resume(run_id: str, body: ResumeRequest, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return call(service.resume_run, s, run_id, body.stopped_confirmed)
