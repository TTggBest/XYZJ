from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from zhiju.auth_context import get_tenant_db
from zhiju.schemas.feishu_sync import FeishuSyncResult
from zhiju.services.feishu_sync import (
    FeishuSyncError,
    sync_channel_schedules,
    sync_channels,
    sync_drama_languages,
    sync_dramas,
    sync_operation_packages,
    sync_work_orders,
)


router = APIRouter(prefix="/v3/feishu-sync", tags=["feishu-sync"])


@router.post("/channel-schedules", response_model=FeishuSyncResult)
def post_channel_schedule_sync(session: Session = Depends(get_tenant_db)) -> FeishuSyncResult:
    try:
        return sync_channel_schedules(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/channels", response_model=FeishuSyncResult)
def post_channel_sync(session: Session = Depends(get_tenant_db)) -> FeishuSyncResult:
    try:
        return sync_channels(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/dramas", response_model=FeishuSyncResult)
def post_drama_sync(session: Session = Depends(get_tenant_db)) -> FeishuSyncResult:
    try:
        return sync_dramas(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/drama-languages", response_model=FeishuSyncResult)
def post_drama_language_sync(session: Session = Depends(get_tenant_db)) -> FeishuSyncResult:
    try:
        return sync_drama_languages(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/work-orders", response_model=FeishuSyncResult)
def post_work_order_sync(session: Session = Depends(get_tenant_db)) -> FeishuSyncResult:
    try:
        return sync_work_orders(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/operation-packages", response_model=FeishuSyncResult)
def post_operation_package_sync(session: Session = Depends(get_tenant_db)) -> FeishuSyncResult:
    try:
        return sync_operation_packages(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


from pydantic import BaseModel,Field
from zhiju.api.v14 import operator
class ChannelMaterialsRequest(BaseModel):
    wiki_token:str=Field(min_length=1)
    refresh_channel_ids:list[str]=Field(default_factory=list)
    preview:bool=True


@router.post('/channel-materials')
def post_channel_materials(body:ChannelMaterialsRequest,session:Session=Depends(get_tenant_db),p=Depends(operator)):
    from zhiju.services.channel_material_sync import sync_channel_materials
    try:return sync_channel_materials(session,body.wiki_token,body.refresh_channel_ids,body.preview)
    except FeishuSyncError as exc:raise HTTPException(409,str(exc)) from exc
