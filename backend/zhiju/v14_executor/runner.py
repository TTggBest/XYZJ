from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Thread
import time

from zhiju.v14_runtime.contract import build_stage_input, validate_result
from zhiju.v14_runtime.market import collect_agent_reach_evidence, build_market_packaging_prompt
from .client import CloudConflict

NODES = ("search", "title", "cover", "description", "community", "merge")


def send_cached(client, envelope, attempt_id, body, path, retry_delay):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"envelope": envelope, "attempt_id": attempt_id, "body": body}, ensure_ascii=False), encoding="utf-8")
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
        except CloudConflict:
            current = client.current(entry["envelope"])
            if not current or current["run_id"] != entry["envelope"]["run_id"]:
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


def run_once(client, model_client, *, cache_root=Path.home() / "Library/Caches/zhiju-v14", evidence_provider=collect_agent_reach_evidence, retry_delay=2, recover=True, stop_event=None):
    root = Path(cache_root)
    if recover and replay_pending(client, root, retry_delay):
        return True
    if stop_event and stop_event.is_set():
        return False
    envelope = client.claim()
    if not envelope:
        return False
    path = root / envelope["run_id"] / "pending.json"
    finished, cancelled = Event(), Event()
    def keepalive():
        while not finished.wait(15):
            try:
                status = client.heartbeat(envelope)["status"]
                if status != "running":
                    cancelled.set()
                    return
            except (PermissionError, CloudConflict):
                cancelled.set()
                return
            except ConnectionError:
                # Cloud never transfers this run automatically while a local call is alive.
                pass
    thread = Thread(target=keepalive, daemon=True)
    thread.start()
    model_client.cancelled = lambda: cancelled.is_set() or bool(stop_event and stop_event.is_set())
    try:
        for node in NODES:
            if node in envelope["accepted_results"]:
                continue
            while True:
                attempt_id = client.begin(envelope, node)
                body = {"claim_id": envelope["claim_id"], "outcome": "accepted", "result": None}
                try:
                    if envelope["account_profile"] != model_client.account_profile:
                        raise RuntimeError("本机 Codex 账号配置与运行绑定不一致")
                    stage = build_stage_input(envelope, node)
                    if node == "merge":
                        result = {"text_complete": True}
                    elif node == "community" and stage.item["community_count"] == 0:
                        result = {"section": "community", "results": []}
                    elif node == "search":
                        evidence = evidence_provider(stage.item)
                        if evidence.get("status") not in {"completed", "partial"}:
                            raise RuntimeError("市场检索失败: " + str(evidence.get("reason", "缺少检索结果")))
                        stage.prompt = build_market_packaging_prompt(stage.item, stage.context["plot_payload"], stage.rules["prompts"]["search"], evidence)
                        result = {"plot_payload": stage.context["plot_payload"], "market_payload": model_client.generate(stage, envelope["model"]), "external_evidence": evidence}
                    else:
                        result = model_client.generate(stage, envelope["model"])
                    normalized = deepcopy(result)
                    issues = validate_result(stage, normalized)
                    if issues:
                        body.update(outcome="content_error", result=result, error="; ".join(issues)[:4000])
                    else:
                        body["result"] = result
                except (RuntimeError, ValueError, KeyError, OSError) as exc:
                    body.update(outcome="system_error", error=str(exc)[:4000])
                try:
                    response = send_cached(client, envelope, attempt_id, body, path, retry_delay)
                except CloudConflict as exc:
                    if body["outcome"] != "accepted" or not str(exc).startswith("V14 验收失败:"):
                        raise
                    body.update(outcome="content_error", error=str(exc)[:4000])
                    response = send_cached(client, envelope, attempt_id, body, path, retry_delay)
                if response["status"] != "running":
                    return True
                if body["outcome"] == "accepted":
                    envelope["accepted_results"][node] = normalized
                    break
                envelope["retry_state"].append({"node_type": node, "outcome": body["outcome"], "error": body.get("error")})
        return True
    finally:
        finished.set()
        thread.join(timeout=21)
