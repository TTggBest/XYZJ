from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.drama_progress import (
    DramaProductionStateRead,
    DramaProductionStateWrite,
    DramaProgressPage,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.drama_progress import (
    get_drama_progress,
    list_drama_progress,
    update_drama_progress,
)


router = APIRouter(prefix="/v3", tags=["drama-progress"])


@router.get("/drama-production", response_model=DramaProgressPage)
def get_progress_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=150),
    sort_order: Literal["asc", "desc"] = "desc",
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
