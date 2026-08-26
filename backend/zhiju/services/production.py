from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import (
    Channel,
    ChannelDnaVersion,
    ChannelPlaylist,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    Drama,
    OperationPackage,
    OperationTask,
    ProductionBatch,
    ProductionNodeRun,
    SystemEvent,
    TaskEvent,
    WorkOrder,
)
from zhiju.schemas.production import TaskCreate
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError, _audit


NODE_SEQUENCE = ("search", "title", "cover", "description", "community", "merge")
PACKAGE_STAGE = {
    "search": "search_ready",
    "title": "title_ready",
    "cover": "cover_ready",
    "description": "text_ready",
    "community": "community_ready",
}


def _native_batch(session: Session, production_date) -> ProductionBatch:
    batch_number = f"ZHJ-{production_date:%Y%m%d}"
    batch = session.scalar(select(ProductionBatch).where(ProductionBatch.batch_number == batch_number))
    if batch is None:
        batch = ProductionBatch(
            batch_number=batch_number, production_date=production_date,
            source="native", status="active",
        )
        session.add(batch)
        session.flush()
    return batch


def _require_productive_channel(session: Session, channel_id: str) -> Channel:
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise NotFoundError("频道不存在")
    if channel.status in {"paused", "archived", "deleted"}:
        raise ConflictError("暂停、归档或删除的频道不能继续生产")
    return channel


def _system_event(
    session: Session,
    entity_type: str,
    entity_id: str,
    old_status: str | None,
    new_status: str,
    reason: str,
) -> None:
    session.add(
        SystemEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            actor_type="system",
            occurred_at=datetime.now(timezone.utc),
        )
    )


def _task_event(session: Session, task: OperationTask, old_status: str | None, reason: str) -> None:
    session.add(
        TaskEvent(
            task_id=task.id,
            old_status=old_status,
            new_status=task.status,
            reason=reason,
            actor_type="system",
            occurred_at=datetime.now(timezone.utc),
        )
    )
    _system_event(session, "operation_task", task.id, old_status, task.status, reason)


def create_task(session: Session, payload: TaskCreate) -> OperationTask:
    existing = session.scalar(select(OperationTask).where(OperationTask.idempotency_key == payload.idempotency_key))
    if existing is not None:
        return existing
    schedule = session.get(ChannelScheduleEntry, payload.schedule_id)
    if schedule is None:
        raise NotFoundError("排期不存在")
    if schedule.status not in {"planned", "reserved", "confirmed"}:
        raise ConflictError("取消、替换或已发布排期不能生成任务")
    _require_productive_channel(session, schedule.channel_id)
    batch = _native_batch(session, payload.task_date)
    task = OperationTask(
        schedule_id=schedule.id,
        batch_id=batch.id,
        channel_id=schedule.channel_id,
        drama_id=schedule.drama_id,
        publish_slot_id=schedule.publish_slot_id,
        playlist_id=schedule.playlist_id,
        task_date=payload.task_date,
        target_publish_date=schedule.publish_date,
        community_count=schedule.community_count,
        source="schedule",
        status="pending_dispatch",
        idempotency_key=payload.idempotency_key,
    )
    session.add(task)
    try:
        session.flush()
        _task_event(session, task, None, "从排期生成任务")
        _audit(session, "task.created", "operation_task", task.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该排期已经生成任务") from exc
    session.refresh(task)
    return task


def list_tasks(
    session: Session,
    *,
    task_date=None,
    channel_id: str | None = None,
    status: str | None = None,
) -> list[OperationTask]:
    statement = select(OperationTask)
    if task_date:
        statement = statement.where(OperationTask.task_date == task_date)
    if channel_id:
        statement = statement.where(OperationTask.channel_id == channel_id)
    if status:
        statement = statement.where(OperationTask.status == status)
    return list(session.scalars(statement.order_by(
        OperationTask.task_date.desc(),
        OperationTask.source_row_number.is_(None),
        OperationTask.source_row_number.asc(),
        OperationTask.created_at.asc(),
    )))


def _latest_nodes(session: Session, work_order_id: str) -> list[ProductionNodeRun]:
    rows = list(
        session.scalars(
            select(ProductionNodeRun)
            .where(ProductionNodeRun.work_order_id == work_order_id)
            .order_by(ProductionNodeRun.sequence_number, ProductionNodeRun.attempt_number.desc())
        )
    )
    latest: dict[str, ProductionNodeRun] = {}
    for row in rows:
        latest.setdefault(row.node_type, row)
    return sorted(latest.values(), key=lambda row: row.sequence_number)


def _detail(session: Session, work_order: WorkOrder) -> dict[str, object]:
    task = session.get(OperationTask, work_order.task_id)
    package = session.scalar(
        select(OperationPackage)
        .where(OperationPackage.work_order_id == work_order.id)
        .order_by(OperationPackage.version_number.desc())
    )
    if task is None or package is None:
        raise RuntimeError("工单关联数据不完整")
    return {"task": task, "work_order": work_order, "package": package, "nodes": _latest_nodes(session, work_order.id)}


def dispatch_task(session: Session, task_id: str) -> dict[str, object]:
    task = session.scalar(select(OperationTask).where(OperationTask.id == task_id).with_for_update())
    if task is None:
        raise NotFoundError("任务不存在")
    _require_productive_channel(session, task.channel_id)
    existing = session.scalar(select(WorkOrder).where(WorkOrder.task_id == task.id))
    if existing is not None:
        return _detail(session, existing)
    if task.status != "pending_dispatch":
        raise ConflictError("只有待下发任务可以下发")
    now = datetime.now(timezone.utc)
    work_order = WorkOrder(
        task_id=task.id,
        batch_id=task.batch_id,
        schedule_id=task.schedule_id,
        channel_id=task.channel_id,
        drama_id=task.drama_id,
        publish_slot_id=task.publish_slot_id,
        playlist_id=task.playlist_id,
        production_date=task.task_date,
        target_publish_date=task.target_publish_date,
        community_count=task.community_count,
        status="queued",
    )
    session.add(work_order)
    session.flush()
    dna_version = session.scalar(
        select(ChannelDnaVersion)
        .where(ChannelDnaVersion.channel_id == task.channel_id, ChannelDnaVersion.status == "active")
        .order_by(ChannelDnaVersion.version_number.desc())
    )
    package = OperationPackage(
        work_order_id=work_order.id,
        batch_id=task.batch_id,
        schedule_id=task.schedule_id,
        channel_id=task.channel_id,
        drama_id=task.drama_id,
        channel_dna_version_id=dna_version.id if dna_version else None,
        version_number=1,
        status="building",
    )
    session.add(package)
    session.flush()
    for sequence, node_type in enumerate(NODE_SEQUENCE, start=1):
        session.add(
            ProductionNodeRun(
                work_order_id=work_order.id,
                package_id=package.id,
                node_type=node_type,
                sequence_number=sequence,
                attempt_number=1,
                status="queued" if sequence == 1 else "pending",
                idempotency_key=f"{work_order.id}:{node_type}:1",
            )
        )
    old_status = task.status
    task.status = "dispatched"
    task.dispatched_at = now
    _task_event(session, task, old_status, "任务已下发并创建生产工单")
    _system_event(session, "work_order", work_order.id, None, "queued", "任务下发")
    _system_event(session, "operation_package", package.id, None, "building", "初始化运营包")
    _audit(session, "task.dispatched", "operation_task", task.id)
    session.commit()
    session.refresh(work_order)
    return _detail(session, work_order)


def list_work_orders(session: Session, *, production_date=None, status: str | None = None) -> list[WorkOrder]:
    statement = select(WorkOrder)
    if production_date:
        statement = statement.where(WorkOrder.production_date == production_date)
    if status:
        statement = statement.where(WorkOrder.status == status)
    return list(session.scalars(statement.order_by(WorkOrder.production_date.desc(), WorkOrder.created_at.desc())))


def summarize_node_progress(nodes: list[ProductionNodeRun]) -> dict[str, object]:
    completed = sum(node.status in {"completed", "skipped"} for node in nodes)
    total = len(NODE_SEQUENCE)
    by_type = {node.node_type: node for node in nodes}
    current_node = None
    for status in ("failed", "running", "queued"):
        current_node = next(
            (
                node_type
                for node_type in NODE_SEQUENCE
                if node_type in by_type and by_type[node_type].status == status
            ),
            None,
        )
        if current_node is not None:
            break
    return {
        "current_node": current_node,
        "completed_nodes": completed,
        "total_nodes": total,
        "progress_percent": int(completed * 100 / total),
    }


def _latest_node_map(
    session: Session, work_order_ids: list[str]
) -> dict[str, dict[str, ProductionNodeRun]]:
    if not work_order_ids:
        return {}
    node_rows = list(
        session.scalars(
            select(ProductionNodeRun)
            .where(ProductionNodeRun.work_order_id.in_(work_order_ids))
            .order_by(
                ProductionNodeRun.work_order_id,
                ProductionNodeRun.sequence_number,
                ProductionNodeRun.attempt_number.desc(),
            )
        )
    )
    latest_nodes: dict[str, dict[str, ProductionNodeRun]] = {}
    for node in node_rows:
        latest_nodes.setdefault(node.work_order_id, {}).setdefault(node.node_type, node)
    return latest_nodes


def _node_payload(node_map: dict[str, ProductionNodeRun]) -> dict[str, dict[str, object]]:
    return {
        node_type: {
            "node_type": node.node_type,
            "status": node.status,
            "attempt_number": node.attempt_number,
            "worker_key": node.worker_key,
            "started_at": node.started_at,
            "completed_at": node.completed_at,
            "error_code": node.error_code,
            "error_message": node.error_message,
        }
        for node_type, node in node_map.items()
    }


def list_work_order_overview(
    session: Session,
    *,
    production_date=None,
    channel_id: str | None = None,
    status: str | None = None,
    package_status: str | None = None,
) -> list[dict[str, object]]:
    latest_package_version = (
        select(func.max(OperationPackage.version_number))
        .where(OperationPackage.work_order_id == WorkOrder.id)
        .correlate(WorkOrder)
        .scalar_subquery()
    )
    statement = (
        select(WorkOrder, OperationTask, ProductionBatch, Channel, Drama, OperationPackage)
        .join(OperationTask, OperationTask.id == WorkOrder.task_id)
        .outerjoin(ProductionBatch, ProductionBatch.id == WorkOrder.batch_id)
        .join(Channel, Channel.id == WorkOrder.channel_id)
        .join(Drama, Drama.id == WorkOrder.drama_id)
        .join(
            OperationPackage,
            and_(
                OperationPackage.work_order_id == WorkOrder.id,
                OperationPackage.version_number == latest_package_version,
            ),
        )
    )
    if production_date:
        statement = statement.where(WorkOrder.production_date == production_date)
    if channel_id:
        statement = statement.where(WorkOrder.channel_id == channel_id)
    if status:
        statement = statement.where(WorkOrder.status == status)
    if package_status:
        statement = statement.where(OperationPackage.status == package_status)
    rows = list(
        session.execute(
            statement.order_by(
                WorkOrder.production_date.desc(),
                OperationTask.source_row_number.is_(None),
                OperationTask.source_row_number.asc(),
                WorkOrder.created_at.asc(),
            )
        )
    )
    work_order_ids = [work_order.id for work_order, *_ in rows]
    latest_nodes = _latest_node_map(session, work_order_ids)

    result = []
    for work_order, task, batch, channel, drama, package in rows:
        node_map = latest_nodes.get(work_order.id, {})
        ordered_nodes = [node_map[node_type] for node_type in NODE_SEQUENCE if node_type in node_map]
        progress = summarize_node_progress(ordered_nodes)
        result.append(
            {
                "work_order_id": work_order.id,
                "task_id": work_order.task_id,
                "package_id": package.id,
                "production_date": work_order.production_date,
                "target_publish_date": work_order.target_publish_date,
                "channel_id": channel.id,
                "youtube_channel_id": channel.youtube_channel_id,
                "channel_name": channel.operational_name or channel.original_name,
                "channel_original_name": channel.original_name,
                "drama_id": drama.id,
                "drama_number": drama.drama_number,
                "business_drama_id": task.source_video_id or str(drama.drama_number),
                "source_row_number": task.source_row_number,
                "drama_code": drama.drama_code,
                "chinese_title": drama.chinese_title,
                "drama_resource_url": drama.baidu_cloud_url,
                "community_count": work_order.community_count,
                "batch_number": batch.batch_number if batch else None,
                "source_video_id": task.source_video_id,
                "source_video_url": task.source_video_url,
                "work_order_status": work_order.status,
                "package_status": package.status,
                **progress,
                "nodes": _node_payload(node_map),
                "started_at": work_order.started_at,
                "completed_at": work_order.completed_at,
                "failure_reason": work_order.failure_reason,
                "created_at": work_order.created_at,
                "updated_at": work_order.updated_at,
            }
        )
    return result


def list_task_overview(
    session: Session,
    *,
    task_date=None,
    channel_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
) -> list[dict[str, object]]:
    latest_package_version = (
        select(func.max(OperationPackage.version_number))
        .where(OperationPackage.work_order_id == WorkOrder.id)
        .correlate(WorkOrder)
        .scalar_subquery()
    )
    statement = (
        select(
            OperationTask,
            Channel,
            Drama,
            ChannelPublishSlot,
            ChannelScheduleEntry,
            ChannelPlaylist,
            WorkOrder,
            OperationPackage,
            ProductionBatch,
        )
        .join(Channel, Channel.id == OperationTask.channel_id)
        .join(Drama, Drama.id == OperationTask.drama_id)
        .outerjoin(ProductionBatch, ProductionBatch.id == OperationTask.batch_id)
        .outerjoin(ChannelPublishSlot, ChannelPublishSlot.id == OperationTask.publish_slot_id)
        .outerjoin(ChannelScheduleEntry, ChannelScheduleEntry.id == OperationTask.schedule_id)
        .outerjoin(ChannelPlaylist, ChannelPlaylist.id == OperationTask.playlist_id)
        .outerjoin(WorkOrder, WorkOrder.task_id == OperationTask.id)
        .outerjoin(
            OperationPackage,
            and_(
                OperationPackage.work_order_id == WorkOrder.id,
                OperationPackage.version_number == latest_package_version,
            ),
        )
    )
    if task_date:
        statement = statement.where(OperationTask.task_date == task_date)
    if channel_id:
        statement = statement.where(OperationTask.channel_id == channel_id)
    if status:
        statement = statement.where(OperationTask.status == status)
    if source:
        statement = statement.where(OperationTask.source == source)
    rows = list(
        session.execute(
            statement.order_by(
                OperationTask.task_date.desc(),
                OperationTask.source_row_number.is_(None),
                OperationTask.source_row_number.asc(),
                OperationTask.created_at.asc(),
            )
        )
    )
    work_order_ids = [
        work_order.id
        for _, _, _, _, _, _, work_order, _, _ in rows
        if work_order is not None
    ]
    latest_nodes = _latest_node_map(session, work_order_ids)
    result = []
    for task, channel, drama, slot, schedule, playlist, work_order, package, batch in rows:
        node_map = latest_nodes.get(work_order.id, {}) if work_order else {}
        ordered_nodes = [node_map[node_type] for node_type in NODE_SEQUENCE if node_type in node_map]
        progress = summarize_node_progress(ordered_nodes)
        result.append(
            {
                "task_id": task.id,
                "schedule_id": task.schedule_id,
                "task_date": task.task_date,
                "target_publish_date": task.target_publish_date,
                "channel_id": channel.id,
                "youtube_channel_id": channel.youtube_channel_id,
                "channel_name": channel.operational_name or channel.original_name,
                "channel_original_name": channel.original_name,
                "drama_id": drama.id,
                "drama_number": drama.drama_number,
                "business_drama_id": task.source_video_id or str(drama.drama_number),
                "source_row_number": task.source_row_number,
                "drama_code": drama.drama_code,
                "chinese_title": drama.chinese_title,
                "drama_resource_url": drama.baidu_cloud_url,
                "publish_slot_id": task.publish_slot_id,
                "slot_type": slot.slot_type if slot else None,
                "slot_number": slot.slot_number if slot else None,
                "slot_local_time": slot.local_time if slot else None,
                "slot_timezone": slot.timezone if slot else None,
                "schedule_status": schedule.status if schedule else None,
                "planned_local_time": schedule.planned_local_time if schedule else None,
                "planned_beijing_time": schedule.planned_beijing_time if schedule else None,
                "planned_utc_time": schedule.planned_utc_time if schedule else None,
                "playlist_id": task.playlist_id,
                "playlist_name": playlist.local_name if playlist else None,
                "playlist_url": playlist.url if playlist else None,
                "community_count": task.community_count,
                "source": task.source,
                "batch_number": batch.batch_number if batch else None,
                "source_video_id": task.source_video_id,
                "source_video_url": task.source_video_url,
                "task_status": task.status,
                "dispatched_at": task.dispatched_at,
                "completed_at": task.completed_at,
                "failure_reason": task.failure_reason,
                "work_order_id": work_order.id if work_order else None,
                "work_order_status": work_order.status if work_order else None,
                "package_id": package.id if package else None,
                "package_status": package.status if package else None,
                **progress,
                "nodes": _node_payload(node_map),
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
        )
    return result


def get_work_order_detail(session: Session, work_order_id: str) -> dict[str, object]:
    work_order = session.get(WorkOrder, work_order_id)
    if work_order is None:
        raise NotFoundError("工单不存在")
    return _detail(session, work_order)


def _latest_node(session: Session, work_order_id: str, node_type: str, *, lock: bool = False) -> ProductionNodeRun:
    statement = (
        select(ProductionNodeRun)
        .where(ProductionNodeRun.work_order_id == work_order_id, ProductionNodeRun.node_type == node_type)
        .order_by(ProductionNodeRun.attempt_number.desc())
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    node = session.scalar(statement)
    if node is None:
        raise NotFoundError("生产节点不存在")
    return node


def start_node(session: Session, work_order_id: str, node_type: str, worker_key: str) -> ProductionNodeRun:
    if node_type not in NODE_SEQUENCE:
        raise NotFoundError("生产节点不存在")
    node = _latest_node(session, work_order_id, node_type, lock=True)
    if node.status != "queued":
        raise ConflictError("只有已排队节点可以开始")
    work_order = session.get(WorkOrder, work_order_id)
    task = session.get(OperationTask, work_order.task_id) if work_order else None
    if work_order is None or task is None:
        raise NotFoundError("工单关联任务不存在")
    _require_productive_channel(session, work_order.channel_id)
    now = datetime.now(timezone.utc)
    node.status = "running"
    node.worker_key = worker_key
    node.started_at = now
    old_work_order_status = work_order.status
    work_order.status = "running"
    work_order.started_at = work_order.started_at or now
    old_task_status = task.status
    task.status = "processing"
    if old_task_status != task.status:
        _task_event(session, task, old_task_status, f"开始生产节点 {node_type}")
    _system_event(session, "production_node_run", node.id, "queued", "running", "工作器领取节点")
    if old_work_order_status != work_order.status:
        _system_event(session, "work_order", work_order.id, old_work_order_status, work_order.status, "开始生产")
    session.commit()
    session.refresh(node)
    return node


def finish_node(
    session: Session,
    work_order_id: str,
    node_type: str,
    *,
    success: bool,
    error_code: str | None = None,
    error_message: str | None = None,
    allow_merge: bool = False,
) -> dict[str, object]:
    node = _latest_node(session, work_order_id, node_type, lock=True)
    if node.status != "running":
        raise ConflictError("只有运行中的节点可以结束")
    work_order = session.get(WorkOrder, work_order_id)
    task = session.get(OperationTask, work_order.task_id) if work_order else None
    package = session.get(OperationPackage, node.package_id)
    if work_order is None or task is None or package is None:
        raise NotFoundError("节点关联数据不存在")
    if success and node_type == "merge" and not allow_merge:
        raise ConflictError("合并节点必须通过运营包合并接口完成")
    if success and node_type != "merge":
        from zhiju.services.package_outputs import validate_node_output

        validate_node_output(session, node)
    now = datetime.now(timezone.utc)
    if not success:
        node.status = "failed"
        node.completed_at = now
        node.error_code = error_code or "NODE_FAILED"
        node.error_message = error_message
        old_work_order_status = work_order.status
        old_task_status = task.status
        old_package_status = package.status
        work_order.status = "failed"
        work_order.failure_reason = error_message or node.error_code
        task.status = "failed"
        task.failure_reason = work_order.failure_reason
        package.status = "failed"
        _task_event(session, task, old_task_status, f"生产节点 {node_type} 失败")
        _system_event(session, "work_order", work_order.id, old_work_order_status, "failed", "生产节点失败")
        _system_event(session, "operation_package", package.id, old_package_status, "failed", "生产节点失败")
        _system_event(session, "production_node_run", node.id, "running", "failed", "节点执行失败")
    else:
        node.status = "completed"
        node.completed_at = now
        _system_event(session, "production_node_run", node.id, "running", "completed", "节点执行完成")
        if node_type == "merge":
            old_work_order_status = work_order.status
            old_task_status = task.status
            old_package_status = package.status
            work_order.status = "completed"
            work_order.completed_at = now
            work_order.failure_reason = None
            task.status = "completed"
            task.completed_at = now
            task.failure_reason = None
            package.status = "review_pending"
            package.ready_at = now
            _task_event(session, task, old_task_status, "运营包合并完成，等待最终审核")
            _system_event(session, "work_order", work_order.id, old_work_order_status, "completed", "所有生产节点完成")
            _system_event(session, "operation_package", package.id, old_package_status, "review_pending", "运营包合并完成")
        else:
            old_package_status = package.status
            package.status = PACKAGE_STAGE[node_type]
            _system_event(session, "operation_package", package.id, old_package_status, package.status, f"{node_type} 节点完成")
            latest = _latest_nodes(session, work_order_id)
            next_node = next((item for item in latest if item.status == "pending"), None)
            if next_node is not None:
                next_node.status = "queued"
                _system_event(session, "production_node_run", next_node.id, "pending", "queued", "前置节点完成")
    session.commit()
    session.refresh(node)
    return _detail(session, work_order)


def review_package(session: Session, package_id: str, decision: str, note: str | None) -> OperationPackage:
    package = session.scalar(select(OperationPackage).where(OperationPackage.id == package_id).with_for_update())
    if package is None:
        raise NotFoundError("运营包不存在")
    if package.status != "review_pending":
        raise ConflictError("只有等待最终审核的运营包可以审核")
    old_status = package.status
    package.status = decision
    package.review_note = note
    if decision == "approved":
        package.approved_at = datetime.now(timezone.utc)
    _system_event(session, "operation_package", package.id, old_status, decision, note or "最终审核")
    _audit(session, "package.reviewed", "operation_package", package.id)
    session.commit()
    session.refresh(package)
    return package


def retry_node(session: Session, work_order_id: str, node_type: str, reason: str) -> dict[str, object]:
    if node_type not in NODE_SEQUENCE:
        raise NotFoundError("生产节点不存在")
    work_order = session.scalar(select(WorkOrder).where(WorkOrder.id == work_order_id).with_for_update())
    if work_order is None:
        raise NotFoundError("工单不存在")
    _require_productive_channel(session, work_order.channel_id)
    task = session.get(OperationTask, work_order.task_id)
    package = session.scalar(
        select(OperationPackage).where(OperationPackage.work_order_id == work_order.id).order_by(OperationPackage.version_number.desc())
    )
    latest = _latest_node(session, work_order_id, node_type, lock=True)
    if task is None or package is None:
        raise NotFoundError("工单关联数据不存在")
    if latest.status != "failed" and package.status != "changes_requested":
        raise ConflictError("只有失败节点或最终审核退回的运营包可以单节点重试")
    next_attempt = latest.attempt_number + 1
    retry = ProductionNodeRun(
        work_order_id=work_order.id,
        package_id=package.id,
        node_type=node_type,
        sequence_number=NODE_SEQUENCE.index(node_type) + 1,
        attempt_number=next_attempt,
        status="queued",
        idempotency_key=f"{work_order.id}:{node_type}:{next_attempt}",
    )
    session.add(retry)
    if node_type != "merge":
        merge = _latest_node(session, work_order_id, "merge")
        if merge.status != "pending":
            merge_attempt = merge.attempt_number + 1
            session.add(
                ProductionNodeRun(
                    work_order_id=work_order.id,
                    package_id=package.id,
                    node_type="merge",
                    sequence_number=6,
                    attempt_number=merge_attempt,
                    status="pending",
                    idempotency_key=f"{work_order.id}:merge:{merge_attempt}",
                )
            )
    old_work_order_status = work_order.status
    old_task_status = task.status
    old_package_status = package.status
    work_order.status = "queued"
    work_order.completed_at = None
    work_order.failure_reason = None
    work_order.attempt_count += 1
    task.status = "processing"
    task.completed_at = None
    task.failure_reason = None
    package.status = "building"
    package.ready_at = None
    package.approved_at = None
    session.flush()
    _task_event(session, task, old_task_status, f"重试生产节点 {node_type}: {reason}")
    _system_event(session, "work_order", work_order.id, old_work_order_status, "queued", reason)
    _system_event(session, "operation_package", package.id, old_package_status, "building", reason)
    _audit(session, "production_node.retried", "production_node_run", retry.id)
    session.commit()
    return _detail(session, work_order)
