from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from zhiju.models import (Channel, Drama, OperationPackage, PackageArtifact, PackageCommunityPost,
                          PackageCoverVariant, PackageDescription, PackageTitle, WorkOrder, OperationTask, Language)
from zhiju.models.v14 import V14Run, V14Setting, V14Attempt
from zhiju.services.production import NODE_SEQUENCE, _require_productive_channel, dispatch_task
from zhiju.services.identity import ConflictError
from zhiju.tenant_repository import require_tenant_entity
from zhiju.schemas.v14 import V14SettingsWrite


def get_settings(session: Session) -> V14Setting | None:
    return session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info["tenant_id"]))


def save_settings(session: Session, payload: dict) -> V14Setting:
    data = V14SettingsWrite.model_validate(payload).model_dump()
    setting = get_settings(session)
    if setting is not None and 'workflow_version_id' not in payload:
        data['workflow_version_id'] = setting.payload.get('workflow_version_id', 'builtin-v14')
    if setting is None:
        setting = V14Setting(tenant_id=session.info["tenant_id"], payload=data)
        session.add(setting)
    else:
        setting.payload = deepcopy(data)
    session.commit()
    return setting


def get_run(session: Session, run_id: str) -> V14Run:
    return require_tenant_entity(session, V14Run, run_id, lock=True)


def start_task(session: Session, task_id: str, *, workflow_version_id: str | None = None) -> V14Run:
    """Dispatch and enqueue the existing V14 workflow as one transaction."""
    try:
        detail = dispatch_task(session, task_id, commit=False)
        run = create_run(session, detail["work_order"].id, commit=False, workflow_version_id=workflow_version_id)
        session.commit()
        return run
    except Exception:
        session.rollback()
        raise


def create_run(session: Session, work_order_id: str, *, commit: bool = True, workflow_version_id: str | None = None) -> V14Run:
    work = require_tenant_entity(session, WorkOrder, work_order_id, lock=True)
    existing = session.scalar(select(V14Run).where(V14Run.work_order_id == work.id,
                                                  V14Run.tenant_id == session.info["tenant_id"]))
    if existing:
        return existing
    package = session.scalar(select(OperationPackage).where(OperationPackage.work_order_id == work.id,
        OperationPackage.tenant_id == session.info["tenant_id"]).order_by(OperationPackage.version_number.desc()))
    if package is None:
        raise ConflictError("工单缺少运营包，请先完成现有分发流程")
    for model in (PackageTitle, PackageDescription, PackageCoverVariant, PackageCommunityPost, PackageArtifact):
        if session.scalar(select(model.id).where(model.package_id == package.id).limit(1)):
            raise ConflictError("已有运营包结果，不能覆盖；请选择尚未生产的工单")
    if package.status != "building" or work.status != "queued":
        raise ConflictError("已有生产状态，不能覆盖；请选择尚未生产的工单")
    setting = get_settings(session)
    if setting is None:
        raise ConflictError("请先配置 V14 执行主机、模型和规则")
    config = setting.payload
    selected = workflow_version_id or config.get('workflow_version_id') or 'builtin-v14'
    bundle = None
    if selected:
        from zhiju.services.workflow_versions import resolve
        bundle = resolve(session, selected)
    task = require_tenant_entity(session, OperationTask, work.task_id)
    if task.schedule_id:
        from zhiju.models import ChannelScheduleEntry
        from zhiju.services.community_requirements import initialize_schedule_community
        schedule = require_tenant_entity(session, ChannelScheduleEntry, task.schedule_id, lock=True)
        count = initialize_schedule_community(session, schedule)
        task.community_count = work.community_count = count
    channel = _require_productive_channel(session, work.channel_id)
    drama = require_tenant_entity(session, Drama, work.drama_id)
    channel_input = config["channel_inputs"].get(channel.id)
    if not channel_input or (not bundle and not config["rules"]):
        raise ConflictError("缺少当前频道 V14 材料或固定规则")
    if channel.default_language:
        from zhiju.services.schedule_youtube import LANGUAGES
        aliases = {key.casefold(): value.casefold() for key, value in LANGUAGES.items()}
        for language in session.scalars(select(Language)):
            for name in (language.code, language.name_zh, language.native_name, language.name_zh.removesuffix("语")):
                if name:
                    aliases[name.casefold()] = language.code.casefold()
        configured = str(channel_input.get("language") or "").strip().casefold()
        expected = channel.default_language.strip().casefold()
        if aliases.get(configured, configured) != aliases.get(expected, expected):
            raise ConflictError("运营包材料语言与当前频道语言不一致，请修正后再启动")
    run = V14Run(tenant_id=session.info["tenant_id"], work_order_id=work.id, package_id=package.id,
        host_id=config["host_id"], account_profile=config["account_profile"], model=config["default_model"],
        rules_snapshot={'skill_bundle': bundle} if bundle else deepcopy(config["rules"]), input_snapshot={
            "channel_id": channel.id, "channel_name": channel.original_name,
            "drama_id": drama.id, "drama_name": drama.chinese_title,
            "drama": {key: getattr(drama, key) for key in ("content_summary", "plot_archive", "plot_pattern", "core_personas", "source_language")},
            "channel": deepcopy(channel_input), "community_count": work.community_count,
            "target_publish_date": str(work.target_publish_date),
            "video_id": task.source_video_id or f"pending_{work.id}", "video_url": task.source_video_url,
        })
    if bundle:
        run.input_snapshot['workflow_version'] = {k: bundle[k] for k in ('id', 'label', 'revision')}
    from zhiju.v14_runtime.contract import build_stage_input
    try:
        build_stage_input({"run_id": work.id, "input_snapshot": run.input_snapshot,
            "rules_snapshot": run.rules_snapshot}, "search")
    except (ValueError, KeyError, TypeError) as exc:
        raise ConflictError(f"运营包配置不完整: {exc}") from exc
    session.add(run)
    if commit:
        session.commit()
    else:
        session.flush()
    return run


def attempts(session, run):
    return list(session.scalars(select(V14Attempt).where(V14Attempt.run_id == run.id).order_by(V14Attempt.created_at, V14Attempt.sequence)))


def active_attempts(session, run):
    floors = run.input_snapshot.get("community_revision_after", {})
    return [a for a in attempts(session, run) if a.sequence > floors.get(a.node_type, 0)]


def execution_status(status, heartbeat):
    """Use the same heartbeat-based interruption state in list and detail."""
    if heartbeat and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    if status == "running" and heartbeat and datetime.now(timezone.utc) - heartbeat > timedelta(seconds=90):
        status = "interrupted"
    return status


def run_read(session, run):
    rows = attempts(session, run)
    status = execution_status(run.status, run.heartbeat_at)
    return {"run_id": run.id, "work_order_id": run.work_order_id, "package_id": run.package_id,
        "workflow_version": run.input_snapshot.get('workflow_version'),
        "status": status, "claim_id": run.claim_id, "model": run.model, "host_id": run.host_id, "error": run.error,
        "attempts": [{"attempt_id": a.id, "node_type": a.node_type, "outcome": a.outcome,
                      "sequence": a.sequence, "error": a.error} for a in rows]}


def envelope(session, run):
    rows = active_attempts(session, run)
    # Serialize accepts across the tenant using the same settings row lock used by submit.
    history = list(session.scalars(select(V14Run).where(V14Run.tenant_id == run.tenant_id, V14Run.id != run.id)))
    history_rows = []
    for old in history:
        for a in active_attempts(session, old):
            if a.outcome == "accepted":
                history_rows.append({"run_id": old.id, "input_snapshot": old.input_snapshot,
                                     "node_type": a.node_type, "payload": a.payload})
    return {**run_read(session, run), "tenant_id": run.tenant_id, "claim_id": run.claim_id,
        "account_profile": run.account_profile, "input_snapshot": run.input_snapshot,
        "rules_snapshot": run.rules_snapshot, "creative_history": history_rows,
        "accepted_results": {a.node_type: a.payload for a in rows if a.outcome == "accepted"},
        "retry_state": [{"node_type": a.node_type, "outcome": a.outcome, "error": a.error} for a in rows]}


def claim_run(session, host_id: str, *, executor_protocol: int = 2):
    session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info["tenant_id"]).with_for_update())
    # Sort only IDs: full Skills JSON snapshots can exceed MySQL's sort buffer.
    run_id = session.scalar(select(V14Run.id).where(V14Run.tenant_id == session.info["tenant_id"],
        V14Run.host_id == host_id, V14Run.status == "queued").order_by(V14Run.created_at).with_for_update().limit(1))
    if run_id is None:
        return None
    run = session.scalar(select(V14Run).where(V14Run.id == run_id).with_for_update())
    if run.rules_snapshot.get('skill_bundle') and executor_protocol < 2:
        raise ConflictError('当前执行器不支持成套 Skills，请更新本机执行器；任务仍保持待执行')
    run.status, run.claim_id = "running", str(uuid4())
    run.heartbeat_at = datetime.now(timezone.utc)
    session.commit()
    return envelope(session, run)


def check_claim(run, claim_id):
    if run.status != "running" or run.claim_id != claim_id:
        raise ConflictError("执行已停止或领取凭证已失效")


def begin_attempt(session, run_id: str, claim_id: str, node_type: str):
    run = get_run(session, run_id)
    check_claim(run, claim_id)
    rows = active_attempts(session, run)
    done = {a.node_type for a in rows if a.outcome == "accepted"}
    expected = next((n for n in NODE_SEQUENCE if n not in done), None)
    if node_type != expected or any(a.outcome == "running" for a in rows):
        raise ConflictError("节点顺序不正确或已有运行中的尝试")
    sequence = 1 + max((a.sequence for a in attempts(session, run) if a.node_type == node_type), default=0)
    from zhiju.services import production
    node = production._latest_node(session, run.work_order_id, node_type, lock=True)
    if node.status == "queued":
        production.start_node(session, run.work_order_id, node_type, run.host_id, commit=False)
    elif node.status != "running" or node.worker_key != run.host_id:
        raise ConflictError("生产节点不属于当前执行")
    attempt = V14Attempt(run_id=run.id, claim_id=claim_id, node_type=node_type, sequence=sequence)
    session.add(attempt)
    session.commit()
    return attempt


def submit_attempt(session, run_id: str, attempt_id: str, payload):
    # A tenant-wide row lock makes full-history validation and acceptance one operation.
    session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info["tenant_id"]).with_for_update())
    run = get_run(session, run_id)
    attempt = require_tenant_entity(session, V14Attempt, attempt_id, lock=True)
    if attempt.run_id != run.id or attempt.claim_id != payload.claim_id or run.claim_id != payload.claim_id:
        raise ConflictError("尝试不属于当前执行")
    if attempt.outcome != "running":
        if attempt.outcome != payload.outcome or attempt.raw_payload != payload.result or attempt.error != payload.error:
            raise ConflictError("同一尝试不能回传不同结果")
        return run_read(session, run)
    check_claim(run, payload.claim_id)
    result = deepcopy(payload.result)
    if payload.outcome == "accepted":
        if payload.result is None:
            raise ConflictError("缺少阶段结果")
        from zhiju.services.v14_outputs import apply_outputs
        apply_outputs(session, run, attempt, result)
    attempt.raw_payload = deepcopy(payload.result)
    attempt.outcome, attempt.payload, attempt.error = payload.outcome, result, payload.error
    run.error = payload.error
    session.flush()
    if payload.outcome == "system_error":
        run.status = "interrupted"
    elif payload.outcome == "content_error":
        failures = sum(a.outcome == "content_error" and a.node_type == attempt.node_type
                       for a in active_attempts(session, run))
        if failures >= 3:
            run.status = "needs_user_review"
    elif attempt.node_type == "merge":
        run.status = "text_ready"
    run.heartbeat_at = datetime.now(timezone.utc)
    session.commit()
    return run_read(session, run)


def cancel_run(session, run_id):
    run = get_run(session, run_id)
    if run.status == "text_ready":
        raise ConflictError("文本已完成，不能取消")
    run.status = "cancelled"
    session.commit()
    return run_read(session, run)


def resume_run(session, run_id, stopped_confirmed):
    run = get_run(session, run_id)
    if not stopped_confirmed:
        raise ConflictError("请先确认原执行器进程已停止")
    rows = attempts(session, run)
    community_failures = [a for a in rows if a.node_type == "community" and a.outcome == "content_error"]
    # Repair the old deterministic zero-post validation bug, not real content failures.
    zero_post_system_failure = (
        run.status == "needs_user_review" and run.input_snapshot["community_count"] == 0
        and run.error == "results_missing" and bool(community_failures)
        and all(a.error == "results_missing" and a.raw_payload == {"section": "community", "results": []}
                for a in community_failures)
        and {"search", "title", "cover", "description"}.issubset(
            {a.node_type for a in rows if a.outcome == "accepted"})
    )
    if run_read(session, run)["status"] not in {"interrupted", "cancelled"} and not zero_post_system_failure:
        raise ConflictError("当前状态不能继续；内容重试耗尽需要人工审核")
    for a in rows:
        if a.outcome == "running":
            a.outcome, a.error = "interrupted", "原执行已停止"
    run.claim_id, run.status, run.error = None, "queued", None
    session.commit()
    return run_read(session, run)
