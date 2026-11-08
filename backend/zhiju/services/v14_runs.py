from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session, load_only

from zhiju.models import (Channel, Drama, OperationPackage, PackageArtifact, PackageCommunityPost,
                          PackageCoverVariant, PackageDescription, PackageTitle, WorkOrder, OperationTask, Language, ChannelProfile, ChannelSchedulePlan)
from zhiju.models.v14 import V14Run, V14Setting, V14Attempt
from zhiju.services.channel_guidance import active_dna, applied_reference, resolve as resolve_guidance
from zhiju.services.production import NODE_SEQUENCE, _require_productive_channel, dispatch_task
from zhiju.services.identity import ConflictError, channel_order_columns, _audit
from zhiju.tenant_repository import require_tenant_entity
from zhiju.schemas.v14 import V14SettingsWrite
from zhiju.workflow_bundles import execution_nodes, is_v20_revision_6


def get_settings(session: Session) -> V14Setting | None:
    return session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info["tenant_id"]))


def save_settings(session: Session, payload: dict) -> V14Setting:
    data = V14SettingsWrite.model_validate(payload).model_dump()
    setting = get_settings(session)
    if setting is not None and 'workflow_version_id' not in payload:
        data['workflow_version_id'] = setting.payload.get('workflow_version_id', 'builtin-v14')
    if setting is not None and 'analysis_skill_version_id' not in payload:
        data['analysis_skill_version_id'] = setting.payload.get('analysis_skill_version_id', 'builtin-xy-yt-report-v2')
    if setting is not None and 'scheduling_skill_version_id' not in payload:
        data['scheduling_skill_version_id'] = setting.payload.get('scheduling_skill_version_id', 'builtin-channel-scheduling-v1')
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
    schedule = None
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
    # Dispatch can precede the first run. Freeze production guidance when the run starts.
    current_dna = active_dna(session, channel.id)
    dna_version_id = current_dna.id if current_dna else work.channel_dna_version_id
    if dna_version_id:
        guidance = resolve_guidance(session, channel.id, dna_version_id, use_plan_snapshot=not current_dna)
        if guidance['source'] != 'legacy_reference' and not guidance['generation_spec']:
            raise ConflictError('频道分析版本缺少生成规范，请补齐对应版本后再生产')
        if guidance['source'] != 'legacy_reference':
            channel_input = {**channel_input, 'generation_spec':guidance['generation_spec'],
                             'analysis_version':{**{k:guidance[k] for k in ('dna_id','run_id','report_id')},'report_type':guidance['mode']}}
    if is_v20_revision_6(bundle):
        if drama.source_language not in {'zh', 'en'}:
            raise ConflictError('请先在剧库登记中文或英语原片语言，供封面正确选角')
        profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel.id))
        if not profile or not profile.title_template:
            raise ConflictError('请先在频道档案登记固定标题模板')
        reference = applied_reference(session, current_dna) if current_dna else None
        language = session.scalar(select(Language).where(Language.code == channel.default_language))
        channel_input = {**channel_input, 'title_template': profile.title_template, 'operating_reference': reference,
                         'market_language_name': (language.native_name or language.name_zh) if language else channel_input['language']}
    assignment = _schedule_assignment(session, schedule) if schedule and schedule.playlist_id else None
    if assignment:
        chosen = assignment['playlist']
        channel_input = {**channel_input, 'playlists': [chosen, *(
            p for p in channel_input.get('playlists', []) if p.get('url') != chosen['url'])]}
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
    if assignment:
        run.input_snapshot['schedule_assignment'] = assignment
    if bundle:
        run.input_snapshot['workflow_version'] = {k: bundle[k] for k in ('id', 'label', 'revision')}
    from zhiju.v14_runtime.contract import build_stage_input
    try:
        build_stage_input({"run_id": work.id, "input_snapshot": run.input_snapshot,
            "rules_snapshot": run.rules_snapshot}, "search")
    except (ValueError, KeyError, TypeError) as exc:
        raise ConflictError(f"运营包配置不完整: {exc}") from exc
    from zhiju.services.channel_readiness import production_material_issues
    missing = production_material_issues(session, channel, channel_input)
    if missing:
        raise ConflictError(f"频道 {channel.operational_name or channel.original_name} 尚未具备生产条件，缺少：" + "、".join(missing))
    sequence = execution_nodes(run.rules_snapshot)
    if sequence != NODE_SEQUENCE:
        from zhiju.models import ProductionNodeRun
        from zhiju.services.production import _latest_nodes
        nodes = {n.node_type: n for n in _latest_nodes(session, work.id)}
        for number, name in enumerate(sequence, 1):
            if name in nodes:
                nodes[name].sequence_number = number
            else:
                session.add(ProductionNodeRun(work_order_id=work.id, package_id=package.id,
                    node_type=name, sequence_number=number, attempt_number=1, status='pending',
                    idempotency_key=f'{work.id}:{name}:1'))
    work.channel_dna_version_id = package.channel_dna_version_id = dna_version_id
    session.add(run)
    if commit:
        session.commit()
    else:
        session.flush()
    return run


def _schedule_assignment(session, schedule):
    from zhiju.services.schedule_planning import available_playlists

    playlist = next((p for p in available_playlists(session, schedule.channel_id)
                     if p['id'] == schedule.playlist_id), None)
    if playlist is None:
        raise ConflictError('排期指定的播放列表已失效或不属于当前频道，请修正排期后再启动')
    assignment = {'schedule_id': schedule.id, 'playlist': playlist}
    key = schedule.idempotency_key
    if key.startswith('plan:'):
        plan = session.get(ChannelSchedulePlan, key.split(':', 2)[1])
        if plan and plan.channel_id == schedule.channel_id and schedule.id in (plan.result or {}).get('schedule_ids', []):
            entry = next((row for row in plan.result['rows'] if row['drama_id'] == schedule.drama_id), {})
            fields = ('operating_reference_version_id', 'target_theme', 'target_direction',
                      'actual_theme', 'actual_direction', 'deviates_from_target', 'fallback_reason')
            assignment.update({key: entry[key] for key in fields if key in entry})
    return assignment


def attempts(session, run):
    return list(session.scalars(select(V14Attempt).where(V14Attempt.run_id == run.id).order_by(V14Attempt.created_at, V14Attempt.sequence)))


def active_attempts(session, run):
    floors = run.input_snapshot.get("community_revision_after", {})
    return [a for a in attempts(session, run) if a.sequence > floors.get(a.node_type, 0)]


def execution_status(status, heartbeat):
    """Heartbeat silence is uncertain connectivity, not a confirmed stopped job."""
    if heartbeat and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    if status == "running" and heartbeat and datetime.now(timezone.utc) - heartbeat > timedelta(seconds=150):
        status = "heartbeat_delayed"
    return status


def run_read(session, run):
    rows = attempts(session, run)
    status = execution_status(run.status, run.heartbeat_at)
    return {"run_id": run.id, "work_order_id": run.work_order_id, "package_id": run.package_id,
        "workflow_version": run.input_snapshot.get('workflow_recovery', {}).get('version') or run.input_snapshot.get('workflow_version'),
        "original_workflow_version": run.input_snapshot.get('workflow_version'),
        "status": status, "heartbeat_at": run.heartbeat_at.replace(tzinfo=timezone.utc).isoformat() if run.heartbeat_at else None, "claim_id": run.claim_id, "model": run.model, "host_id": run.host_id, "error": run.error,
        "attempts": [{"attempt_id": a.id, "node_type": a.node_type, "outcome": a.outcome,
                      "sequence": a.sequence, "error": a.error} for a in rows]}


def execution_rules(session, run):
    rules = run.rules_snapshot
    if run.input_snapshot.get('workflow_recovery'):
        from zhiju.services.workflow_versions import resolve
        rules = {**rules, 'skill_bundle': resolve(session, run.input_snapshot['workflow_recovery']['version']['id'])}
    return rules


def envelope(session, run):
    rows = active_attempts(session, run)
    rules = execution_rules(session, run)
    # Serialize accepts across the tenant using the same settings row lock used by submit.
    history = list(session.scalars(select(V14Run).options(load_only(V14Run.id, V14Run.input_snapshot))
        .where(V14Run.tenant_id == run.tenant_id, V14Run.id != run.id)))
    history_rows = []
    for old in history:
        for a in active_attempts(session, old):
            if a.outcome == "accepted":
                history_rows.append({"run_id": old.id, "input_snapshot": old.input_snapshot,
                                     "node_type": a.node_type, "payload": a.payload,
                                     "accepted_at": a.updated_at.isoformat(), "attempt_id": a.id})
    if "cover_scene" in execution_nodes(rules):
        history_rows.sort(key=lambda row: (row["accepted_at"], row["attempt_id"]))
    planning_ids = {a.node_type: a.payload['history_reference_ids'] for a in rows
                    if a.outcome == 'running' and a.node_type in {'cover_scene', 'community_scene'}
                    and a.payload is not None}
    latest_failures = {a.node_type: a.id for a in rows if a.outcome == "content_error"}
    return {"planning_history_ids": planning_ids, "node_sequence": execution_nodes(rules), **run_read(session, run), "tenant_id": run.tenant_id, "claim_id": run.claim_id,
        "account_profile": run.account_profile, "input_snapshot": run.input_snapshot,
        "rules_snapshot": rules, "creative_history": history_rows,
        "accepted_results": {a.node_type: a.payload for a in rows if a.outcome == "accepted"},
        "retry_state": [{"node_type": a.node_type, "outcome": a.outcome, "error": a.error,
                         **({"result": a.raw_payload} if latest_failures.get(a.node_type) == a.id else {})} for a in rows]}


def claim_read(session, run):
    """Deliver the immutable Skills once; fetch model inputs at each stage."""
    return {**run_read(session, run), 'tenant_id': run.tenant_id,
            'account_profile': run.account_profile, 'staged_inputs': True,
            'node_sequence': execution_nodes(execution_rules(session, run)),
            'rules_snapshot': execution_rules(session, run),
            'accepted_nodes': [a.node_type for a in active_attempts(session, run)
                               if a.outcome == 'accepted']}


def attempt_input(session, run, attempt_id, claim_id, external_evidence=None):
    """Keep full history/validator context on the server, preserving the model request."""
    check_claim(run, claim_id)
    attempt = require_tenant_entity(session, V14Attempt, attempt_id)
    if attempt.run_id != run.id or attempt.claim_id != claim_id or attempt.outcome != 'running':
        raise ConflictError('阶段输入不属于当前执行')
    from zhiju.v14_runtime.contract import build_stage_input
    data = envelope(session, run)
    if external_evidence is not None:
        data['external_evidence'] = external_evidence
    stage = build_stage_input(data, attempt.node_type)
    from zhiju.v14_executor.runner import apply_content_recovery
    apply_content_recovery(stage, data, attempt.node_type)
    # The server still validates against the full, unchanged context on submission.
    # Only search needs its frozen plot locally to attach retrieval evidence.
    return {key: getattr(stage, key) for key in ('node_type', 'prompt', 'schema', 'item', 'rules')} | {
        'context': {'plot_payload': stage.context['plot_payload']} if attempt.node_type == 'search' else {}}


def claim_run(session, host_id: str, *, executor_protocol: int = 2, claim_id: str | None = None, run_id: str | None = None):
    preferred_id=run_id
    session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info["tenant_id"]).with_for_update())
    if executor_protocol >= 4 and claim_id:
        existing = session.scalar(select(V14Run).where(V14Run.host_id == host_id,
            V14Run.claim_id == claim_id, V14Run.status == 'running'))
        if existing is not None:
            return claim_read(session, existing)
    from zhiju.services.executor_queue import admission
    if not admission(session):return None
    # Sort only IDs: full Skills JSON snapshots can exceed MySQL's sort buffer.
    run_id = session.scalar(select(V14Run.id).join(WorkOrder, WorkOrder.id == V14Run.work_order_id).join(Channel, Channel.id == WorkOrder.channel_id).where(V14Run.tenant_id == session.info["tenant_id"],
        V14Run.host_id == host_id, V14Run.status == "queued",*([V14Run.id==preferred_id] if preferred_id else [])).order_by(*channel_order_columns(), V14Run.created_at, V14Run.id).with_for_update().limit(1))
    if run_id is None:
        return None
    run = session.scalar(select(V14Run).where(V14Run.id == run_id).with_for_update())
    from zhiju.workflow_bundles import executor_protocol as required_protocol
    if executor_protocol < required_protocol(execution_rules(session, run)):
        raise ConflictError('当前执行器不支持成套 Skills，请更新本机执行器；任务仍保持待执行')
    run.status, run.claim_id = "running", claim_id if executor_protocol >= 4 and claim_id else str(uuid4())
    run.heartbeat_at = datetime.now(timezone.utc)
    from zhiju.services.executor_queue import reserve
    reserve(session,'operation_package',run)
    session.commit()
    return claim_read(session, run) if executor_protocol >= 4 else envelope(session, run)


def check_claim(run, claim_id):
    if run.status != "running" or run.claim_id != claim_id:
        raise ConflictError("执行已停止或领取凭证已失效")


def begin_attempt(session, run_id: str, claim_id: str, node_type: str, *, reuse_running=False):
    run = get_run(session, run_id)
    check_claim(run, claim_id)
    rows = active_attempts(session, run)
    if reuse_running:
        existing = next((a for a in rows if a.outcome == 'running'
                         and a.node_type == node_type and a.claim_id == claim_id), None)
        if existing is not None:
            return existing
    done = {a.node_type for a in rows if a.outcome == "accepted"}
    expected = next((n for n in execution_nodes(execution_rules(session, run)) if n not in done), None)
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
    if node_type in {'cover_scene', 'community_scene'}:
        from zhiju.v14_runtime.contract import build_stage_input
        stage = build_stage_input(envelope(session, run), node_type)
        attempt.payload = {'history_reference_ids': [row['reference_id'] for row in stage.context['planning_history']]}
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
        retry_after = run.input_snapshot.get("manual_content_retry_after", {}).get(attempt.node_type, 0)
        failures = sum(a.outcome == "content_error" and a.node_type == attempt.node_type
                       and a.sequence > retry_after for a in active_attempts(session, run))
        if failures >= 6:
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


def resume_run(session, run_id, stopped_confirmed, *, retry_content=False):
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
    manual_retry = run.status == "needs_user_review" and retry_content
    if run_read(session, run)["status"] not in {"interrupted", "cancelled", "heartbeat_delayed"} and not zero_post_system_failure and not manual_retry:
        raise ConflictError("当前状态不能继续；自动重新规划后仍未通过，需要修正失败原因后重试")
    if manual_retry:
        active = active_attempts(session, run)
        done = {a.node_type for a in active if a.outcome == "accepted"}
        node = next((n for n in execution_nodes(execution_rules(session, run)) if n not in done), None)
        failed = [a for a in active if a.node_type == node and a.outcome == "content_error"]
        if not failed:
            raise ConflictError("当前阶段没有可重新尝试的内容失败记录")
        # Keep all evidence and accepted outputs; only start a new bounded retry budget.
        run.input_snapshot = {**run.input_snapshot, "manual_content_retry_after": {
            **run.input_snapshot.get("manual_content_retry_after", {}),
            node: max(a.sequence for a in failed),
        }}
    for a in rows:
        if a.outcome == "running":
            a.outcome, a.error = "interrupted", "原执行已停止"
    from zhiju.services.executor_queue import release_stopped_run
    release_stopped_run(session,'operation_package',run.id)
    run.claim_id, run.status, run.error = None, "queued", None
    session.commit()
    return run_read(session, run)


def correct_workflow(session, run_id, version_id, stopped_confirmed, reason):
    """Pin an explicit input-build correction for an interrupted cover, without enqueueing."""
    session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info['tenant_id']).with_for_update())
    run = get_run(session, run_id)
    if not stopped_confirmed or run.status != 'interrupted':
        raise ConflictError('仅允许在确认执行器停止后纠正已中断工单')
    previous = run.input_snapshot.get('workflow_recovery')
    if previous:
        if previous['version']['id'] == version_id:
            return run_read(session, run)
        raise ConflictError('本工单已有版本纠正记录，请先审阅现有纠正')
    rows = active_attempts(session, run)
    if {a.node_type for a in rows if a.outcome == 'accepted'} != {'search', 'title'}:
        raise ConflictError('此入口仅修复已完成搜索和标题、尚未完成封面的工单')
    if not any(a.node_type == 'cover' and a.outcome == 'system_error' for a in rows):
        raise ConflictError('当前封面阶段没有系统错误')
    from zhiju.services.workflow_versions import resolve
    bundle = resolve(session, version_id)
    original = run.rules_snapshot.get('skill_bundle', {})
    if bundle['label'] != original.get('label') or bundle['revision'] <= original.get('revision', 0):
        raise ConflictError('纠正必须选择同一工作流的已发布新修订')
    from zhiju.v14_runtime.contract import build_stage_input
    current = envelope(session, run)
    replacement = {**current, 'rules_snapshot': {**run.rules_snapshot, 'skill_bundle': bundle}}
    if build_stage_input(current, 'cover').schema != build_stage_input(replacement, 'cover').schema:
        raise ConflictError('输入修复不能改变封面输出结构')
    run.input_snapshot = {**run.input_snapshot, 'workflow_recovery': {
        'version': {k: bundle[k] for k in ('id', 'label', 'revision')},
        'reason': reason,
        'corrected_at': datetime.now(timezone.utc).isoformat(),
    }}
    session.commit()
    return run_read(session, run)


def upgrade_workflow(session, run_id, version_id, stopped_confirmed, reason, *, commit=True):
    """Move paused V16 work after title to V17, preserving accepted outputs and original snapshots."""
    session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info['tenant_id']).with_for_update())
    run = get_run(session, run_id)
    if not stopped_confirmed or run.status != 'interrupted':
        raise ConflictError('请确认执行器已停止；只允许切换已中断工单')
    current_rules = execution_rules(session, run)
    if current_rules.get('skill_bundle', {}).get('id') == version_id:
        return run_read(session, run)
    from zhiju.services.workflow_versions import resolve
    bundle = resolve(session, version_id)
    target_rules = {'skill_bundle': bundle}
    target_nodes = ('search', 'title', 'cover_scene', 'cover', 'description', 'community_scene', 'community', 'merge')
    if (current_rules.get('skill_bundle', {}).get('label') != 'V16'
            or bundle['label'] != 'V17' or execution_nodes(target_rules) != target_nodes):
        raise ConflictError('此入口只支持将 V16 的中断工单切换到 V17 八节点流程')
    rows = active_attempts(session, run)
    if {a.node_type for a in rows if a.outcome == 'accepted'} != {'search', 'title'} or any(a.outcome == 'running' for a in rows):
        raise ConflictError('只允许保留已完成搜索和标题、尚未完成下游的工单切换')
    from zhiju.v14_runtime.contract import build_stage_input
    try:
        build_stage_input({**envelope(session, run), 'rules_snapshot': target_rules}, 'cover_scene')
    except (ValueError, KeyError, TypeError) as exc:
        raise ConflictError(f'既有资料无法接入 V17: {exc}') from exc
    from zhiju.models import ProductionNodeRun
    from zhiju.services.production import _latest_nodes
    nodes = {n.node_type: n for n in _latest_nodes(session, run.work_order_id)}
    for number, name in enumerate(target_nodes, 1):
        if name in nodes:
            node = nodes[name]
            node.sequence_number = number
            if name not in {'search', 'title'}:
                node.status, node.worker_key = 'pending', None
        else:
            session.add(ProductionNodeRun(work_order_id=run.work_order_id, package_id=run.package_id,
                node_type=name, sequence_number=number, attempt_number=1,
                status='queued' if name == 'cover_scene' else 'pending',
                idempotency_key=f'{run.work_order_id}:{name}:1'))
    previous = run.input_snapshot.get('workflow_recovery')
    recovery = {'version': {k: bundle[k] for k in ('id', 'label', 'revision')},
                'reason': reason, 'corrected_at': datetime.now(timezone.utc).isoformat()}
    if previous:
        recovery['previous'] = deepcopy(previous)
    run.input_snapshot = {**run.input_snapshot, 'workflow_recovery': recovery}
    run.claim_id = None
    if commit:
        session.commit()
    else:
        session.flush()
    return run_read(session, run)


def check_connection(session,run_id,claim_id,local_state):
    """A bound executor probes its actual processes before recovering a silent claim."""
    run=get_run(session,run_id)
    if run.claim_id!=claim_id or run.status!='running':
        return {**run_read(session,run),'recovered':False}
    if local_state=='active':
        run.heartbeat_at=datetime.now(timezone.utc)
        session.commit()
        return {**run_read(session,run),'recovered':False}
    if local_state=='stopped' and execution_status(run.status,run.heartbeat_at)=='heartbeat_delayed':
        result=resume_run(session,run.id,True)
        _audit(session,'v14.connection_recovered','work_order',run.work_order_id)
        session.commit()
        return {**result,'recovered':True}
    return {**run_read(session,run),'recovered':False}
