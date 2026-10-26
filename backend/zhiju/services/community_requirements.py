"""Edit community requirements without regenerating accepted upstream content."""
from copy import deepcopy

from sqlalchemy import select, func

from zhiju.models import AuditEvent, ChannelScheduleEntry, OperationTask, WorkOrder, OperationPackage, PackageCommunityPost, ProductionNodeRun
from zhiju.models.v14 import V14Run, V14Setting
from zhiju.services.identity import ConflictError, _audit
from zhiju.services import v14_runs, production
from zhiju.tenant_repository import require_tenant_entity


def initialize_schedule_community(session, schedule):
    """Resolve the old Feishu default zero, never an explicitly saved zero."""
    if schedule.source_type != "feishu" or schedule.community_count != 0:
        return schedule.community_count
    explicit = session.scalar(select(AuditEvent.id).where(
        AuditEvent.action == "community.requirement_updated",
        AuditEvent.entity_type == "channel_schedule_entry", AuditEvent.entity_id == schedule.id).limit(1))
    if explicit:
        return 0
    daily_count = session.scalar(select(func.count()).select_from(ChannelScheduleEntry).where(
        ChannelScheduleEntry.channel_id == schedule.channel_id,
        func.date(ChannelScheduleEntry.planned_beijing_time) == schedule.planned_beijing_time.date(),
        ChannelScheduleEntry.status.notin_(["cancelled", "replaced"])))
    schedule.community_count = 2 if daily_count == 1 else 1
    _audit(session, "community.requirement_initialized", "channel_schedule_entry", schedule.id,
        f"旧飞书默认零值按北京时间当日 {daily_count} 条初始化为 {schedule.community_count} 套")
    return schedule.community_count


def update_community(session, kind, entity_id, count):
    session.scalar(select(V14Setting).with_for_update())
    schedule = task = None
    if kind == "schedules":
        schedule = require_tenant_entity(session, ChannelScheduleEntry, entity_id, lock=True)
        task = session.scalar(select(OperationTask).where(OperationTask.schedule_id == schedule.id).with_for_update())
    else:
        task = require_tenant_entity(session, OperationTask, entity_id, lock=True)
        if task.schedule_id:
            schedule = require_tenant_entity(session, ChannelScheduleEntry, task.schedule_id, lock=True)
    work = session.scalar(select(WorkOrder).where(WorkOrder.task_id == task.id).with_for_update()) if task else None
    run = session.scalar(select(V14Run).where(V14Run.work_order_id == work.id).with_for_update()) if work else None
    old_count = work.community_count if work else task.community_count if task else schedule.community_count
    if old_count == count:
        if count == 0 and schedule:
            _audit(session, "community.requirement_updated", "channel_schedule_entry", schedule.id,
                "操作者明确保留零社群")
            session.commit()
        return {"community_count": count, "run": v14_runs.run_read(session, run) if run else None}
    if run and run.status in {"running", "queued"}:
        raise ConflictError("V14 正在执行或排队，请等待完成后再调整社群数量")
    if work and not run and work.status != "queued":
        raise ConflictError("非 V14 已执行工单不能自动调整社群数量")
    if work and run:
        package = session.scalar(select(OperationPackage).where(OperationPackage.work_order_id == work.id).order_by(OperationPackage.version_number.desc()).limit(1))
        if not run or run.status != "text_ready" or old_count != 0 or count == 0:
            raise ConflictError("已下发工单目前只支持为零社群已完成任务补产；已有社群结果不会被覆盖")
        if package.status != "review_pending" or session.scalar(select(PackageCommunityPost.id).where(PackageCommunityPost.package_id == package.id).limit(1)):
            raise ConflictError("已有社群内容或运营包已审核，不能自动覆盖")
        rows = v14_runs.attempts(session, run)
        if not {"search", "title", "cover", "description"}.issubset({a.node_type for a in rows if a.outcome == "accepted"}):
            raise ConflictError("缺少已接受上游结果，不能仅补产社群")
        snapshot = deepcopy(run.input_snapshot)
        snapshot["community_count"] = count
        snapshot["community_revision_after"] = {node: max((a.sequence for a in rows if a.node_type == node), default=0) for node in ("community", "merge")}
        # Check the actual frozen community assets before changing business state.
        from zhiju.v14_runtime.contract import build_stage_input
        try:
            build_stage_input({**v14_runs.envelope(session, run), "input_snapshot": snapshot}, "community")
        except (ValueError, KeyError, TypeError) as exc:
            raise ConflictError(f"社群材料不完整: {exc}") from exc
        run.input_snapshot = snapshot
        run.status, run.claim_id, run.error = "queued", None, None
        for node in ("community", "merge"):
            previous = production._latest_node(session, work.id, node, lock=True)
            number = previous.attempt_number + 1
            session.add(ProductionNodeRun(work_order_id=work.id, package_id=package.id, node_type=node,
                sequence_number=production.NODE_SEQUENCE.index(node) + 1, attempt_number=number,
                status="queued" if node == "community" else "pending",
                idempotency_key=f"{work.id}:{node}:{number}"))
        work.status, work.completed_at = "queued", None
        task.status, task.completed_at = "processing", None
        package.status, package.ready_at = "building", None
        production._task_event(session, task, "completed", f"社群数量从 {old_count} 调整为 {count}，仅补产社群及合成")
    for row in (schedule, task, work):
        if row:
            row.community_count = count
    _audit(session, "community.requirement_updated", "channel_schedule_entry" if schedule else "operation_task", schedule.id if schedule else task.id)
    session.commit()
    return {"community_count": count, "run": v14_runs.run_read(session, run) if run else None}
