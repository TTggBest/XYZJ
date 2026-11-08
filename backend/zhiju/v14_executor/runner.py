from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Thread
import time

from zhiju.v14_runtime.contract import StageInput, build_stage_input, validate_result
from zhiju.v14_runtime.market import collect_agent_reach_evidence, build_market_packaging_prompt
from .client import CloudConflict, CloudNotFound
from .codex import CoverContentError, TitleContentError
from .execution_state import ExecutionState

NODES = ("search", "title", "cover", "description", "community", "merge")


def send_cached(client, envelope, attempt_id, body, path, retry_delay):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    identity = {k: envelope[k] for k in ('run_id', 'work_order_id', 'claim_id') if k in envelope}
    temporary.write_text(json.dumps({"envelope": identity, "attempt_id": attempt_id, "body": body}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    for retry in range(3):
        try:
            result = client.submit(envelope, attempt_id, body)
            path.unlink()
            return result
        except ConnectionError:
            if retry == 2:
                raise
            time.sleep(retry_delay)


def replay_pending(client, root, retry_delay=2):
    root = Path(root)
    # A lost response cannot trigger regeneration, even after restarting this process.
    for cached in sorted(root.glob("*/pending.json")):
        entry = json.loads(cached.read_text())
        try:
            send_cached(client, entry["envelope"], entry["attempt_id"], entry["body"], cached, retry_delay)
        except (CloudConflict, CloudNotFound) as rejected:
            try:
                current = client.current(entry["envelope"])
            except CloudNotFound:
                current = None  # The work order itself has been deleted.
            removed = not current or current["run_id"] != entry["envelope"]["run_id"]
            if not removed:
                # A 404 for an attempt in a live run is a real protocol error.
                if isinstance(rejected, CloudNotFound):
                    raise
                stale = current.get("claim_id") != entry["envelope"]["claim_id"]
                stopped = current["status"] in {"cancelled", "text_ready"}
                if not stale and not stopped:
                    raise
            # Retain generated evidence, but do not let a deliberately invalidated claim
            # poison the outbound queue forever. Never swallow an unrelated 409.
            cached.replace(cached.with_name(entry["attempt_id"] + ".abandoned.json"))
            continue
        # The original cloud run must be resumed explicitly, never guessed from disk.
        return True
    return False


def apply_content_recovery(stage, envelope, node):
    failures = [row for row in envelope.get("retry_state", [])
                if row["node_type"] == node and row.get("outcome") == "content_error"]
    if not failures:
        return
    feedback = "\n".join(str(row.get("error") or "") for row in failures[-3:])
    if node in {"title", "cover_scene", "cover"}:
        feedback = str(failures[-1].get("error") or "")
        previous = failures[-1].get("result")
        reference_errors = all(
            "source_anchor_not_in_plot" in issue or issue.strip() == "v18_title_key_detail_missing_from_title"
            for issue in feedback.split(";") if issue.strip()
        )
        instruction = (
            "以上次完整结果为修复基线，按报错定位受影响的组和字段，保留未受错误影响的公开标题、主互动及其他内容。"
            "先对照原始剧情判断事实是否成立：事实已成立而source_anchor未逐字匹配时，只修真实连续原文引用及必要依赖；"
            "retained_form不匹配时，先修追踪记录。retained_form必须取最终标题中的真实连续原文，跨片段时包含中间原文，"
            "不可自行插入分号，也不让公开标题迁就取证格式。若核对后确有事实、关系、语言或安全缺陷，"
            "才修改相关公开表达、互动及必要依赖；不能换一段真实引用替无依据内容背书。"
            "引用或追踪报错本身不代表创意失败，不因失败次数要求换掉有效方案。保持原输出结构、固定资产和其他已通过阶段。"
        )
        if len(failures) >= 3 and not reference_errors:
            instruction += ("自动重新规划仅限已确认的语义失败部分：在原始剧情与当前承诺内调整受影响的切入或表达，"
                "继续保留无关组的有效内容，不放宽校验。")
        locations = []
        if node == "title" and isinstance(previous, dict) and "v18_title_key_detail_missing_from_title" in feedback:
            for result in previous.get("results", []):
                for row in result.get("directions", []):
                    title = " ".join(str(row.get("title") or "").casefold().split())
                    for detail in row.get("title_detail_realization", []):
                        form = " ".join(str(detail.get("retained_form") or "").casefold().split())
                        if detail.get("disposition") == "retain" and (not form or form not in title):
                            locations.append(f"第{row.get('index')}组 detail_id={detail.get('detail_id')}，"
                                "失败字段retained_form：记录不是标题的连续原文；该报错不判定标题遗漏事实。")
        baseline = ("\n上次完整结果（修复基线，保留无关内容）：\n" + json.dumps(previous, ensure_ascii=False)
                    if previous is not None else "")
        stage.prompt += ("\n\n" + instruction + "\n最近校验原因：\n" + feedback
                         + ("\n具体记录定位：\n" + "\n".join(locations) if locations else "") + baseline)
        return
    instruction = "根据以下校验失败原因修正本阶段内容，保持剧情事实、频道定位、固定资产和输出结构不变。"
    if len(failures) >= 3:
        instruction = ("自动重新规划：原方案已连续失败，不要继续仅替换个别词语。"
            "先在内部判断失败源于切入角度、表达方向、构图还是结构；"
            "对适用的创作部分选择不同且有原始事实依据的角度或方案，再生成本阶段结果。"
            "如果只是结构问题则修正结构，不要无故改剧情；不得放宽校验、虚构事实、"
            "更换频道定位、修改固定资产或重做已通过阶段。最终只返回原定结构的结果。")
    previous = failures[-1].get("result")
    rejected = ("\n上次未通过内容摘录（仅用于避开旧方案）：\n" + json.dumps(previous, ensure_ascii=False)[:6000]) if previous is not None else ""
    stage.prompt += "\n\n" + instruction + "\n最近校验原因：\n" + feedback + rejected


def run_once(client, model_client, *, cache_root=Path.home() / "Library/Caches/zhiju-v14", evidence_provider=collect_agent_reach_evidence, retry_delay=2, recover=True, stop_event=None, envelope=None):
    root = Path(cache_root)
    if recover and replay_pending(client, root, retry_delay):
        return True
    if stop_event and stop_event.is_set():
        return False
    envelope = envelope or client.claim()
    if not envelope:
        return False
    envelope.setdefault('accepted_results', {})
    staged = envelope.get('staged_inputs', False)
    def prepare(attempt, node, evidence=None):
        if staged:
            return StageInput(**client.stage_input(envelope, attempt, evidence),
                              skill_bundle=envelope['rules_snapshot'].get('skill_bundle'))
        return build_stage_input({**envelope, **({'external_evidence': evidence} if evidence is not None else {})}, node)
    path = root / envelope["run_id"] / "pending.json"
    state=ExecutionState(root / envelope["run_id"] / "execution.json",envelope)
    terminal=False
    previous_process_changed=getattr(model_client,'process_changed',lambda pid:None)
    def process_changed(pid):
        previous_process_changed(pid);state.update(model_pid=pid)
    model_client.process_changed=process_changed
    finished, cancelled = Event(), Event()
    def keepalive():
        while not finished.wait(15):
            try:
                status = client.heartbeat(envelope)["status"]
                state.update(last_heartbeat=time.time())
                if status != "running":
                    cancelled.set()
                    return
            except (PermissionError, CloudConflict):
                cancelled.set()
                return
            except (ConnectionError,RuntimeError):
                # A temporary HTTP failure must not silently kill keepalive.
                # Cloud never transfers this run automatically while a local call is alive.
                pass
    thread = Thread(target=keepalive, daemon=True)
    thread.start()
    model_client.cancelled = lambda: cancelled.is_set() or bool(stop_event and stop_event.is_set())
    try:
        for node in envelope.get("node_sequence", NODES):
            if node in envelope["accepted_results"] or node in envelope.get('accepted_nodes', []):
                continue
            while True:
                attempt_id = client.begin(envelope, node)
                body = {"claim_id": envelope["claim_id"], "outcome": "accepted", "result": None}
                if hasattr(model_client, 'phase_trace'):
                    model_client.phase_trace = []
                try:
                    if envelope["account_profile"] != model_client.account_profile:
                        raise RuntimeError("本机 Codex 账号配置与运行绑定不一致")
                    stage = prepare(attempt_id, node)
                    if node == "merge":
                        result = {"text_complete": True}
                    elif node == "community_scene" and stage.item["community_count"] == 0:
                        result = {"section": "community_scene", "plans": []}
                    elif node == "community" and stage.item["community_count"] == 0:
                        result = {"section": "community", "results": []}
                    elif node == "search":
                        if stage.skill_bundle and evidence_provider is collect_agent_reach_evidence:
                            from zhiju.workflow_bundles import invoke_bundle, archive_from_snapshot
                            evidence = invoke_bundle(archive_from_snapshot(stage.skill_bundle), 'evidence', {'item': stage.item})
                        else:
                            evidence = evidence_provider(stage.item)
                        # Keep failed retrieval evidence so Find can use its
                        # existing plot-only fallback instead of stopping the run.
                        if stage.skill_bundle:
                            stage = prepare(attempt_id, node, evidence)
                        else:
                            stage.prompt = build_market_packaging_prompt(stage.item, stage.context["plot_payload"], stage.rules["prompts"]["search"], evidence)
                        if not staged:
                            apply_content_recovery(stage, envelope, node)
                        result = {"plot_payload": stage.context["plot_payload"], "market_payload": model_client.generate(stage, envelope["model"]), "external_evidence": evidence}
                    else:
                        if not staged:
                            apply_content_recovery(stage, envelope, node)
                        result = model_client.generate(stage, envelope["model"])
                    normalized = deepcopy(result)
                    issues = [] if staged else validate_result(stage, normalized)
                    if issues:
                        body.update(outcome="content_error", result=result, error="; ".join(issues)[:4000])
                    else:
                        body["result"] = result
                except (CoverContentError, TitleContentError) as exc:
                    body.update(outcome="content_error", result=exc.result, error=str(exc)[:4000])
                except (RuntimeError, ValueError, KeyError, OSError) as exc:
                    body.update(outcome="system_error", error=str(exc)[:4000])
                finally:
                    trace = getattr(model_client, 'phase_trace', None)
                    if node in {"title", "cover"} and trace:
                        trace_path = root / envelope['run_id'] / (f"{attempt_id}.{node}_phases.json")
                        trace_path.parent.mkdir(parents=True, exist_ok=True)
                        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                try:
                    response = send_cached(client, envelope, attempt_id, body, path, retry_delay)
                except CloudConflict as exc:
                    if body["outcome"] != "accepted" or not str(exc).startswith(("V14 验收失败:", "V14 结构或输入不完整:")):
                        raise
                    body.update(outcome="content_error", error=str(exc)[:4000])
                    response = send_cached(client, envelope, attempt_id, body, path, retry_delay)
                if response["status"] != "running":
                    terminal=True
                    return True
                if body["outcome"] == "accepted":
                    envelope["accepted_results"][node] = normalized
                    break
                if not staged:
                    envelope["retry_state"].append({"node_type": node, "outcome": body["outcome"], "error": body.get("error"), "result": body.get("result")})
        terminal=True
        return True
    finally:
        state.update(finished=terminal)
        finished.set()
        thread.join(timeout=21)
