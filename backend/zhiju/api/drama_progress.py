from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.config import get_settings
from zhiju.schemas.drama_progress import (
    DramaProductionExclusionWrite,
    DramaProductionStateRead,
    DramaProductionStateWrite,
    DramaProgressPage,
    ZhiheProgressSyncResult,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.drama_progress import (
    complete_cloud_download,
    get_drama_progress,
    list_drama_progress,
    set_production_exclusion,
    update_drama_progress,
)
from zhiju.services.zhihe_progress_sync import (
    ZhiheApiError,
    ZhiheProgressClient,
    sync_zhihe_progress,
)


router = APIRouter(prefix="/v3", tags=["drama-progress"])


@router.get("/drama-production", response_model=DramaProgressPage)
def get_progress_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=150),
    sort_order: Literal["asc", "desc"] = "asc",
    search: str | None = None,
    batch_name: str | None = None,
    overall_status: str | None = None,
    current_node: str | None = None,
    session: Session = Depends(get_db),
) -> DramaProgressPage:
    return list_drama_progress(
        session,
        page=page,
        page_size=page_size,
        sort_order=sort_order,
        search=search,
        batch_name=batch_name,
        overall_status=overall_status,
        current_node=current_node,
    )


@router.get(
    "/dramas/{drama_id}/production-state",
    response_model=DramaProductionStateRead,
)
def get_progress_item(
    drama_id: str,
    session: Session = Depends(get_db),
) -> DramaProductionStateRead:
    try:
        return get_drama_progress(session, drama_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/dramas/{drama_id}/production-state",
    response_model=DramaProductionStateRead,
)
def put_progress_item(
    drama_id: str,
    payload: DramaProductionStateWrite,
    session: Session = Depends(get_db),
) -> DramaProductionStateRead:
    try:
        return update_drama_progress(session, drama_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/dramas/{drama_id}/production-state/cloud-download/complete",
    response_model=DramaProductionStateRead,
)
def post_cloud_download_complete(
    drama_id: str,
    session: Session = Depends(get_db),
) -> DramaProductionStateRead:
    try:
        return complete_cloud_download(session, drama_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put(
    "/dramas/{drama_id}/production-state/exclusion",
    response_model=DramaProductionStateRead,
)
def put_production_exclusion(
    drama_id: str,
    payload: DramaProductionExclusionWrite,
    session: Session = Depends(get_db),
) -> DramaProductionStateRead:
    try:
        return set_production_exclusion(session, drama_id, excluded=payload.excluded)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/integrations/zhihe/drama-progress/sync",
    response_model=ZhiheProgressSyncResult,
)
def post_zhihe_progress_sync(
    updated_after: datetime | None = None,
    session: Session = Depends(get_db),
) -> ZhiheProgressSyncResult:
    settings = get_settings()
    if not settings.zhihe_api_base_url or not settings.zhihe_api_token:
        raise HTTPException(status_code=409, detail="尚未配置智核 API 地址或访问令牌")
    client = ZhiheProgressClient(
        base_url=settings.zhihe_api_base_url,
        token=settings.zhihe_api_token,
    )
    try:
        return ZhiheProgressSyncResult(
            **sync_zhihe_progress(session, client, updated_after=updated_after)
        )
    except ZhiheApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
