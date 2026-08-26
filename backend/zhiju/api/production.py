from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.production import (
    CommunityBatchWrite,
    CommunityPostRead,
    CoverBatchWrite,
    CoverRead,
    DescriptionRead,
    DescriptionWrite,
    NodeFinish,
    NodeRetry,
    NodeRunRead,
    NodeStart,
    PackageRead,
    PackageMergeResult,
    PackageCopyMark,
    PackageCopyProgress,
    PackageOperationOverview,
    PackageOutputsRead,
    PackageReview,
    SimilarityCheckRead,
    SimilarityCheckWrite,
    TaskCreate,
    TaskOverview,
    TaskRead,
    TitleBatchWrite,
    TitleRead,
    ValidationRead,
    ValidationWrite,
    WorkOrderDetail,
    WorkOrderOverview,
    WorkOrderRead,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError
from zhiju.services.production import (
    create_task,
    dispatch_task,
    finish_node,
    get_work_order_detail,
    list_work_order_overview,
    list_tasks,
    list_task_overview,
    list_work_orders,
    retry_node,
    review_package,
    start_node,
)
from zhiju.services.package_outputs import (
    add_validation,
    get_package_outputs,
    get_package_copy_progress,
    list_package_operation_overview,
    list_similarity_checks,
    merge_package,
    mark_package_output_copied,
    upsert_similarity_check,
    write_community,
    write_covers,
    write_description,
    write_titles,
)


router = APIRouter(prefix="/v3", tags=["production"])


def _raise(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, NotFoundError) else 409, detail=str(exc))


@router.get("/tasks", response_model=list[TaskRead])
def get_tasks(
    task_date: date | None = None,
    channel_id: str | None = None,
    task_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> list[TaskRead]:
    return list_tasks(session, task_date=task_date, channel_id=channel_id, status=task_status)


@router.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def post_task(payload: TaskCreate, session: Session = Depends(get_db)) -> TaskRead:
    try:
        return create_task(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/tasks/overview", response_model=list[TaskOverview])
def get_task_overview(
    task_date: date | None = None,
    channel_id: str | None = None,
    task_status: str | None = Query(default=None, alias="status"),
    source: str | None = None,
    session: Session = Depends(get_db),
) -> list[TaskOverview]:
    return list_task_overview(
        session,
        task_date=task_date,
        channel_id=channel_id,
        status=task_status,
        source=source,
    )


@router.post("/tasks/{task_id}/dispatch", response_model=WorkOrderDetail)
def post_task_dispatch(task_id: str, session: Session = Depends(get_db)) -> WorkOrderDetail:
    try:
        return dispatch_task(session, task_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/work-orders", response_model=list[WorkOrderRead])
def get_work_orders(
    production_date: date | None = None,
    work_order_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> list[WorkOrderRead]:
    return list_work_orders(session, production_date=production_date, status=work_order_status)


@router.get("/work-orders/overview", response_model=list[WorkOrderOverview])
def get_work_order_overview(
    production_date: date | None = None,
    channel_id: str | None = None,
    work_order_status: str | None = Query(default=None, alias="status"),
    package_status: str | None = None,
    session: Session = Depends(get_db),
) -> list[WorkOrderOverview]:
    return list_work_order_overview(
        session,
        production_date=production_date,
        channel_id=channel_id,
        status=work_order_status,
        package_status=package_status,
    )


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderDetail)
def get_work_order(work_order_id: str, session: Session = Depends(get_db)) -> WorkOrderDetail:
    try:
        return get_work_order_detail(session, work_order_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/work-orders/{work_order_id}/nodes/{node_type}/start",
    response_model=NodeRunRead,
)
def post_node_start(
    work_order_id: str,
    node_type: str,
    payload: NodeStart,
    session: Session = Depends(get_db),
) -> NodeRunRead:
    try:
        return start_node(session, work_order_id, node_type, payload.worker_key)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/work-orders/{work_order_id}/nodes/{node_type}/finish",
    response_model=WorkOrderDetail,
)
def post_node_finish(
    work_order_id: str,
    node_type: str,
    payload: NodeFinish,
    session: Session = Depends(get_db),
) -> WorkOrderDetail:
    try:
        return finish_node(
            session,
            work_order_id,
            node_type,
            success=payload.success,
            error_code=payload.error_code,
            error_message=payload.error_message,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/work-orders/{work_order_id}/nodes/{node_type}/retry",
    response_model=WorkOrderDetail,
)
def post_node_retry(
    work_order_id: str,
    node_type: str,
    payload: NodeRetry,
    session: Session = Depends(get_db),
) -> WorkOrderDetail:
    try:
        return retry_node(session, work_order_id, node_type, payload.reason)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/packages/operations-overview", response_model=list[PackageOperationOverview])
def get_package_operation_overview(
    production_date: date | None = None,
    channel_id: str | None = None,
    package_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> list[PackageOperationOverview]:
    return list_package_operation_overview(
        session,
        production_date=production_date,
        channel_id=channel_id,
        package_status=package_status,
    )


@router.get("/packages/{package_id}/copy-progress", response_model=PackageCopyProgress)
def get_copy_progress(package_id: str, session: Session = Depends(get_db)) -> PackageCopyProgress:
    try:
        return get_package_copy_progress(session, package_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.put("/packages/{package_id}/copy-progress", response_model=PackageCopyProgress)
def put_copy_progress(
    package_id: str,
    payload: PackageCopyMark,
    session: Session = Depends(get_db),
) -> PackageCopyProgress:
    try:
        return mark_package_output_copied(session, package_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/packages/{package_id}/review", response_model=PackageRead)
def post_package_review(
    package_id: str,
    payload: PackageReview,
    session: Session = Depends(get_db),
) -> PackageRead:
    try:
        return review_package(session, package_id, payload.decision, payload.note)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/packages/{package_id}/outputs", response_model=PackageOutputsRead)
def get_outputs(package_id: str, session: Session = Depends(get_db)) -> PackageOutputsRead:
    try:
        return get_package_outputs(session, package_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/packages/{package_id}/outputs/titles", response_model=list[TitleRead])
def post_titles(
    package_id: str,
    payload: TitleBatchWrite,
    session: Session = Depends(get_db),
) -> list[TitleRead]:
    try:
        return write_titles(session, package_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/packages/{package_id}/outputs/covers", response_model=list[CoverRead])
def post_covers(
    package_id: str,
    payload: CoverBatchWrite,
    session: Session = Depends(get_db),
) -> list[CoverRead]:
    try:
        return write_covers(session, package_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/packages/{package_id}/outputs/description", response_model=DescriptionRead)
def post_description(
    package_id: str,
    payload: DescriptionWrite,
    session: Session = Depends(get_db),
) -> DescriptionRead:
    try:
        return write_description(session, package_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/packages/{package_id}/outputs/community", response_model=list[CommunityPostRead])
def post_community(
    package_id: str,
    payload: CommunityBatchWrite,
    session: Session = Depends(get_db),
) -> list[CommunityPostRead]:
    try:
        return write_community(session, package_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/packages/{package_id}/validations", response_model=ValidationRead)
def post_validation(
    package_id: str,
    payload: ValidationWrite,
    session: Session = Depends(get_db),
) -> ValidationRead:
    try:
        return add_validation(session, package_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/packages/{package_id}/similarity-checks",
    response_model=list[SimilarityCheckRead],
)
def get_similarity_checks(
    package_id: str,
    result: Literal["pass", "warning", "fail"] | None = None,
    session: Session = Depends(get_db),
) -> list[SimilarityCheckRead]:
    try:
        return list_similarity_checks(session, package_id, result=result)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.put(
    "/packages/{package_id}/similarity-checks/{compared_package_id}",
    response_model=SimilarityCheckRead,
)
def put_similarity_check(
    package_id: str,
    compared_package_id: str,
    payload: SimilarityCheckWrite,
    session: Session = Depends(get_db),
) -> SimilarityCheckRead:
    try:
        return upsert_similarity_check(session, package_id, compared_package_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/packages/{package_id}/merge", response_model=PackageMergeResult)
def post_merge(package_id: str, session: Session = Depends(get_db)) -> PackageMergeResult:
    try:
        return merge_package(session, package_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc
