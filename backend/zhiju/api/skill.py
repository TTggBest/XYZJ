from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.skill import (
    SkillCreate,
    SkillDetail,
    SkillRead,
    SkillUpdate,
    SkillVersionCreate,
    SkillVersionRead,
    SkillVersionUpdate,
)
from zhiju.services.identity import ConflictError
from zhiju.services.skill import (
    SkillNotFoundError,
    create_skill,
    create_skill_version,
    get_skill_detail,
    get_skill_version,
    list_skill_versions,
    list_skills,
    publish_skill_version,
    update_skill,
    update_skill_version,
)


router = APIRouter(prefix="/v3", tags=["skills"])


def _raise(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(exc, SkillNotFoundError) else 409,
        detail=str(exc),
    )


@router.get("/skills", response_model=list[SkillRead])
def get_skills(
    skill_status: str | None = Query(default=None, alias="status"),
    category: str | None = None,
    query: str | None = None,
    session: Session = Depends(get_db),
) -> list[SkillRead]:
    return list_skills(
        session, status=skill_status, category=category, query=query
    )


@router.post("/skills", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
def post_skill(payload: SkillCreate, session: Session = Depends(get_db)) -> SkillRead:
    try:
        return create_skill(session, payload)
    except ConflictError as exc:
        raise _raise(exc) from exc


@router.get("/skills/{skill_id}", response_model=SkillDetail)
def get_skill(skill_id: str, session: Session = Depends(get_db)) -> SkillDetail:
    try:
        return get_skill_detail(session, skill_id)
    except SkillNotFoundError as exc:
        raise _raise(exc) from exc


@router.patch("/skills/{skill_id}", response_model=SkillRead)
def patch_skill(
    skill_id: str, payload: SkillUpdate, session: Session = Depends(get_db)
) -> SkillRead:
    try:
        return update_skill(session, skill_id, payload)
    except (SkillNotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/skills/{skill_id}/versions", response_model=list[SkillVersionRead]
)
def get_skill_versions(
    skill_id: str, session: Session = Depends(get_db)
) -> list[SkillVersionRead]:
    try:
        return list_skill_versions(session, skill_id)
    except SkillNotFoundError as exc:
        raise _raise(exc) from exc


@router.post(
    "/skills/{skill_id}/versions",
    response_model=SkillVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def post_skill_version(
    skill_id: str,
    payload: SkillVersionCreate,
    session: Session = Depends(get_db),
) -> SkillVersionRead:
    try:
        return create_skill_version(session, skill_id, payload)
    except (SkillNotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/skills/{skill_id}/versions/{version_id}", response_model=SkillVersionRead
)
def get_skill_version_detail(
    skill_id: str, version_id: str, session: Session = Depends(get_db)
) -> SkillVersionRead:
    try:
        return get_skill_version(session, skill_id, version_id)
    except SkillNotFoundError as exc:
        raise _raise(exc) from exc


@router.put(
    "/skills/{skill_id}/versions/{version_id}", response_model=SkillVersionRead
)
def put_skill_version(
    skill_id: str,
    version_id: str,
    payload: SkillVersionUpdate,
    session: Session = Depends(get_db),
) -> SkillVersionRead:
    try:
        return update_skill_version(session, skill_id, version_id, payload)
    except (SkillNotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/skills/{skill_id}/versions/{version_id}/publish",
    response_model=SkillVersionRead,
)
def post_skill_version_publish(
    skill_id: str, version_id: str, session: Session = Depends(get_db)
) -> SkillVersionRead:
    try:
        return publish_skill_version(session, skill_id, version_id)
    except (SkillNotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc
