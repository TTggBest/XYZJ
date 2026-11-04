from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Thread
import time

from zhiju.v14_runtime.contract import StageInput, build_stage_input, validate_result
from zhiju.v14_runtime.market import collect_agent_reach_evidence, build_market_packaging_prompt
from .client import CloudConflict, CloudNotFound
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


def run_once(client, model_client, *, cache_root=Path.home() / "Library/Caches/zhiju-v14", evidence_provider=collect_agent_reach_evidence, retry_delay=2, recover=True, stop_event=None):
    root = Path(cache_root)
    if recover and replay_pending(client, root, retry_delay):
        return True
    if stop_event and stop_event.is_set():
        return False
    envelope = client.claim()
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
    model_client.process_changed=lambda pid:state.update(model_pid=pid)
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
                except (RuntimeError, ValueError, KeyError, OSError) as exc:
                    body.update(outcome="system_error", error=str(exc)[:4000])
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
