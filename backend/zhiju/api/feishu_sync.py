from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.feishu_sync import FeishuSyncResult
from zhiju.services.feishu_sync import FeishuSyncError, sync_channels, sync_dramas, sync_operation_packages, sync_work_orders


router = APIRouter(prefix="/v3/feishu-sync", tags=["feishu-sync"])


@router.post("/channels", response_model=FeishuSyncResult)
def post_channel_sync(session: Session = Depends(get_db)) -> FeishuSyncResult:
    try:
        return sync_channels(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/dramas", response_model=FeishuSyncResult)
def post_drama_sync(session: Session = Depends(get_db)) -> FeishuSyncResult:
    try:
        return sync_dramas(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/work-orders", response_model=FeishuSyncResult)
def post_work_order_sync(session: Session = Depends(get_db)) -> FeishuSyncResult:
    try:
        return sync_work_orders(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/operation-packages", response_model=FeishuSyncResult)
def post_operation_package_sync(session: Session = Depends(get_db)) -> FeishuSyncResult:
    try:
        return sync_operation_packages(session)
    except FeishuSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
