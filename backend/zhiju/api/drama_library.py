from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.drama_library import (
    DramaLibraryBulkRequest,
    DramaLibraryBulkResult,
    DramaLibraryCsvRequest,
    DramaLibraryDetail,
    DramaLibraryPage,
    DramaLibraryUpdate,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.drama_library import (
    bulk_upsert_dramas,
    get_drama_library_detail,
    list_drama_library,
    parse_drama_csv,
    update_drama_library_item,
)
from zhiju.services.identity import ConflictError


router = APIRouter(prefix="/v3", tags=["drama-library"])


def _raise(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, NotFoundError) else 409, detail=str(exc))


@router.get("/dramas/library", response_model=DramaLibraryPage)
def get_library(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=10, le=100),
    search: str | None = None,
    drama_status: str | None = Query(default=None, alias="status"),
    batch_name: str | None = None,
    expires_from: datetime | None = None,
    expires_to: datetime | None = None,
    session: Session = Depends(get_db),
) -> DramaLibraryPage:
    return list_drama_library(
        session,
        page=page,
        page_size=page_size,
        search=search,
        status=drama_status,
        batch_name=batch_name,
        expires_from=expires_from,
        expires_to=expires_to,
    )


@router.get("/dramas/{drama_id}", response_model=DramaLibraryDetail)
def get_library_item(drama_id: str, session: Session = Depends(get_db)) -> DramaLibraryDetail:
    try:
        return get_drama_library_detail(session, drama_id)
    except NotFoundError as exc:
        raise _raise(exc) from exc


@router.patch("/dramas/{drama_id}", response_model=DramaLibraryDetail)
def patch_library_item(
    drama_id: str,
    payload: DramaLibraryUpdate,
    session: Session = Depends(get_db),
) -> DramaLibraryDetail:
    try:
        return update_drama_library_item(session, drama_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/dramas/bulk", response_model=DramaLibraryBulkResult, status_code=status.HTTP_201_CREATED)
def post_library_bulk(
    payload: DramaLibraryBulkRequest,
    session: Session = Depends(get_db),
) -> DramaLibraryBulkResult:
    try:
        return bulk_upsert_dramas(session, payload)
    except ConflictError as exc:
        raise _raise(exc) from exc


@router.post("/dramas/bulk-csv", response_model=DramaLibraryBulkResult, status_code=status.HTTP_201_CREATED)
def post_library_bulk_csv(
    payload: DramaLibraryCsvRequest,
    session: Session = Depends(get_db),
) -> DramaLibraryBulkResult:
    try:
        return bulk_upsert_dramas(session, parse_drama_csv(payload.content))
    except ConflictError as exc:
        raise _raise(exc) from exc
