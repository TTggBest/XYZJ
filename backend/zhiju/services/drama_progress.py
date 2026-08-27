from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models import Drama, DramaProductionState
from zhiju.schemas.drama_progress import DramaProductionStateWrite
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import _audit
from zhiju.services.operations import normalize_drama_title


NODE_DEFINITIONS = (
    ("cloud_download", "网盘下载", "cloud_download_status"),
    ("parameter_normalization", "统一参数", "parameter_normalization_status"),
    ("subtitle_extraction", "字幕提取", "subtitle_extraction_status"),
    ("guishou_upload", "鬼手上传", "guishou_upload_status"),
    ("role_extraction", "角色提取", "role_extraction_status"),
    ("production_completion", "制作完成", "production_completion_status"),
)


def _value(state: object, field: str) -> str:
    if isinstance(state, dict):
        return str(state.get(field) or "not_started")
    return str(getattr(state, field, "not_started"))


def calculate_progress(state: object) -> tuple[int, str, str | None]:
    statuses = [_value(state, field) for _, _, field in NODE_DEFINITIONS]
    completed = sum(status == "completed" for status in statuses)
    if "failed" in statuses:
        overall = "failed"
        current = NODE_DEFINITIONS[statuses.index("failed")][0]
    elif completed == len(statuses):
        overall = "completed"
        current = None
    elif all(status == "not_started" for status in statuses):
        overall = "not_started"
        current = NODE_DEFINITIONS[0][0]
    else:
        overall = "in_progress"
        current = NODE_DEFINITIONS[next(index for index, status in enumerate(statuses) if status != "completed")][0]
    return round(completed * 100 / len(statuses)), overall, current


def validate_progress_order(state: object) -> None:
    statuses = [_value(state, field) for _, _, field in NODE_DEFINITIONS]
    for index, status in enumerate(statuses):
        if status == "not_started":
            continue
        unfinished = next((previous for previous in range(index) if statuses[previous] != "completed"), None)
        if unfinished is not None:
            raise ValueError(
                f"{NODE_DEFINITIONS[index][1]}前置节点未完成：{NODE_DEFINITIONS[unfinished][1]}"
            )


def production_state_payload(
    state: DramaProductionState | None,
    drama_id: str,
) -> dict[str, object]:
    node_values = {
        field: _value(state or {}, field)
        for _, _, field in NODE_DEFINITIONS
    }
    progress_percent, overall_status, current_node = calculate_progress(node_values)
    return {
        "id": state.id if state else None,
        "drama_id": drama_id,
        **node_values,
        "episode_count": state.episode_count if state else None,
        "total_duration_seconds": state.total_duration_seconds if state else None,
        "source_type": state.source_type if state else "manual",
        "source_external_id": state.source_external_id if state else None,
        "source_updated_at": state.source_updated_at if state else None,
        "source_synced_at": state.source_synced_at if state else None,
        "last_error": state.last_error if state else None,
        "progress_percent": progress_percent,
        "overall_status": overall_status,
        "current_node": current_node,
        "updated_at": state.updated_at if state else None,
    }


def get_drama_progress(session: Session, drama_id: str) -> dict[str, object]:
    drama = session.get(Drama, drama_id)
    if drama is None:
        raise NotFoundError("剧目不存在")
    state = session.scalar(
        select(DramaProductionState).where(DramaProductionState.drama_id == drama_id)
    )
    return production_state_payload(state, drama_id)


def update_drama_progress(
    session: Session,
    drama_id: str,
    payload: DramaProductionStateWrite,
) -> dict[str, object]:
    drama = session.get(Drama, drama_id)
    if drama is None:
        raise NotFoundError("剧目不存在")
    validate_progress_order(payload)
    state = session.scalar(
        select(DramaProductionState).where(DramaProductionState.drama_id == drama_id)
    )
    if state is None:
        state = DramaProductionState(drama_id=drama_id)
        session.add(state)
    for field, value in payload.model_dump().items():
        setattr(state, field, value)
    state.source_type = "manual"
    _audit(session, "drama.production_progress_updated", "drama", drama_id)
    session.commit()
    session.refresh(state)
    return production_state_payload(state, drama_id)


def list_drama_progress(
    session: Session,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    batch_name: str | None = None,
    overall_status: str | None = None,
    current_node: str | None = None,
) -> dict[str, object]:
    statement = (
        select(Drama, DramaProductionState)
        .outerjoin(DramaProductionState, DramaProductionState.drama_id == Drama.id)
        .order_by(Drama.source_row_number.is_(None), Drama.source_row_number, Drama.drama_number)
    )
    if search:
        normalized = normalize_drama_title(search)
        statement = statement.where(
            (Drama.normalized_title.contains(normalized))
            | (Drama.drama_code.contains(search.strip()))
        )
    if batch_name:
        statement = statement.where(Drama.batch_name == batch_name)
    rows = []
    for drama, state in session.execute(statement):
        item = {
            **production_state_payload(state, drama.id),
            "drama_number": drama.drama_number,
            "drama_code": drama.drama_code,
            "chinese_title": drama.chinese_title,
            "batch_name": drama.batch_name,
        }
        if overall_status and item["overall_status"] != overall_status:
            continue
        if current_node and item["current_node"] != current_node:
            continue
        rows.append(item)
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": ceil(total / page_size) if total else 0,
    }

