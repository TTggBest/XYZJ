from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

from . import canonical as c
from .channel import channel_theme_contract, title_channel_context
from .market import MARKET_PACKAGING_SCHEMA, build_market_packaging_prompt, market_context_for_title, validate_market_packaging_evidence
from .prompts import build_prompt, STAGE_DIRECTIVES
from .rules import using_rules
from .preflight import stage_preflight_issues

STAGES = {"search": "xy-find", "title": "xy-title", "cover": "xy-cover", "description": "xy-place", "community": "xy-post"}
PLOT_FIELDS = {"内容概述": "content_summary", "剧情档案": "plot_archive", "剧情套路": "plot_pattern", "核心人设": "core_personas"}


def validate_static_inputs(data: dict, rules: dict) -> None:
    """Reject configuration faults before freezing a run or spending any model calls."""
    channel = data["channel"]
    for key in ("language", "gender", "direction", "generation_spec"):
        if not isinstance(channel.get(key), str) or not channel[key].strip():
            raise ValueError(f"缺少频道材料: {key}")
    title_channel_context(channel["generation_spec"])
    assets = channel.get("description_fixed_assets")
    if not isinstance(assets, dict) or not str(assets.get("subscribe_line") or "").strip():
        raise ValueError("description_fixed_assets 缺少 subscribe_line")
    disclaimers = assets.get("disclaimer_lines", [])
    if not isinstance(disclaimers, list) or any(not isinstance(s, str) or not s.strip() for s in disclaimers):
        raise ValueError("description_fixed_assets.disclaimer_lines 不完整")
    playlists = channel.get("playlists")
    if not isinstance(playlists, list) or not playlists or any(not isinstance(row, dict) or not row.get("name") or not row.get("url") for row in playlists):
        raise ValueError("缺少完整频道 playlists（name/url）")
    if rules["machine_contracts"]["description"].get("description_contract", {}).get("channel_hashtag_whitelist_required"):
        whitelist = channel.get("channel_hashtag_whitelist")
        if not isinstance(whitelist, dict):
            raise ValueError("缺少 channel_hashtag_whitelist")
        candidates = whitelist.get("additional_candidates")
        mandatory = whitelist.get("mandatory_hashtags")
        target = whitelist.get("target_language_tags")
        count = int(whitelist.get("selection_count") or 12)
        if not isinstance(candidates, list) or not isinstance(mandatory, list) or not isinstance(target, list) or not target or not set(target).issubset(candidates) or len(candidates) < count - len(mandatory):
            raise ValueError("channel_hashtag_whitelist 候选或目标语言标签不完整")
    if data["community_count"]:
        footer = channel.get("community_footer_cta")
        for key in ("full_video_cta", "subscribe_cta", "share_cta", "layout_style"):
            if not isinstance(footer, dict) or not str(footer.get(key) or "").strip():
                raise ValueError(f"community_footer_cta 缺少 {key}")


def bundled_rules():
    root = Path(__file__).parent / "resources"
    names = {"search": "find", "title": "title", "cover": "cover", "description": "place", "community": "post"}
    rules = {"version": "V14", "prompts": {key: (root / f"{name}_prompt.md").read_text() for key, name in names.items()},
        "machine_contracts": {key: json.loads((root / f"{name}_rules.json").read_text()) for key, name in
            {"title": "title", "cover": "cover", "description": "description", "community": "community"}.items()},
        "schemas": {key: deepcopy(c.schema_for(stage, {"workflow_contract_version": 2, "community_count": 1, "community_output_version": 2})) for key, stage in STAGES.items() if key != "search"},
        "directives": deepcopy(STAGE_DIRECTIVES),
        "semantic_contract": {"version": 11, "dynamic_channel_theme_grounding_required": True, "fixed_localized_title_candidates": False}}
    rules["schemas"]["search"] = deepcopy(MARKET_PACKAGING_SCHEMA)
    return rules


@dataclass
class StageInput:
    node_type: str
    prompt: str
    schema: dict
    item: dict
    context: dict
    rules: dict


def build_stage_input(envelope: dict, node_type: str) -> StageInput:
    data = deepcopy(envelope["input_snapshot"])
    rules = deepcopy(envelope["rules_snapshot"])
    channel = data["channel"]
    validate_static_inputs(data, rules)
    for field in PLOT_FIELDS.values():
        if not data["drama"].get(field):
            raise ValueError(f"缺少剧情字段: {field}")
    title_channel_context(channel["generation_spec"])
    item = {"drama_name": data["drama_name"], "video_id": data.get("video_id") or f"pending_{envelope['run_id']}",
        "url": data.get("video_url") or "", "channel": data["channel_name"],
        "language": channel["language"], "gender": channel["gender"], "direction": channel["direction"],
        "slot": data["target_publish_date"], "workflow_contract_version": 2,
        "community_output_version": 2, "community_count": data["community_count"], "need_community": data["community_count"] > 0}
    plot = {"section": "search", "results": [{"plot_fields": {k: data["drama"][v] for k, v in PLOT_FIELDS.items()}}]}
    c.normalize_identity(plot, item)
    accepted = envelope.get("accepted_results", {})
    search = accepted.get("search", {})
    identity = {k: c.first_result(plot)[k] for k in c.IDENTITY_PROPERTIES}
    context = {"task": item, "identity": identity, "plot_payload": plot,
        "semantic_contract": rules["semantic_contract"],
        "channel_snapshot": channel["generation_spec"], "channel_theme_contract": channel_theme_contract(item, plot),
        "playlists": channel.get("playlists", []), "creative_slot": {"creative_slot_id": envelope["run_id"]},
        "description_fixed_assets": channel["description_fixed_assets"], "description_assets_frozen": True,
        "community_footer_cta": channel.get("community_footer_cta", {}),
        "title_rule_contract": rules["machine_contracts"]["title"].get("title_contract", {}), "cover_rule_contract": rules["machine_contracts"]["cover"],
        "description_rule_contract": rules["machine_contracts"]["description"].get("description_contract", {}),
        "community_rule_contract": rules["machine_contracts"]["community"],
        "title_payload": accepted.get("title", {}), "cover_payload": accepted.get("cover", {}), "place_payload": accepted.get("description", {}),
        "market_packaging": market_context_for_title(search.get("market_payload", {})),
        "channel_hashtag_whitelist": channel.get("channel_hashtag_whitelist", {}), "creative_history": [], "visual_history": []}
    grouped = {}
    for row in envelope.get("creative_history", []):
        previous = row["input_snapshot"]
        history = grouped.setdefault(row["run_id"], {"channel": previous["channel_name"], "language": previous["channel"]["language"], "drama_name": previous["drama_name"], "video_id": previous.get("video_id", "")})
        key = {"title": "title_payload", "cover": "cover_payload", "description": "place_payload", "community": "post_payload"}.get(row["node_type"])
        if key:
            history[key] = row["payload"]
        if row["node_type"] == "cover":
            for group, cover in enumerate(c.cover_rows(row["payload"]), 1):
                context["visual_history"].append({**cover, "source_group_index": str(group), "channel": previous["channel_name"], "drama_name": previous["drama_name"], "video_id": previous.get("video_id", "")})
    context["creative_history"] = [h for h in grouped.values() if h["drama_name"] == data["drama_name"]]
    feedback = [r["error"] for r in envelope.get("retry_state", []) if r["node_type"] == node_type and r.get("error")]
    if node_type == "merge":
        return StageInput(node_type, "", {}, item, context, rules)
    schema = deepcopy(rules["schemas"][node_type])
    if node_type == "community":
        schema["properties"]["results"]["minItems"] = item["community_count"]
        schema["properties"]["results"]["maxItems"] = item["community_count"]
    context["output_schema"] = schema
    if node_type == "search":
        prompt = build_market_packaging_prompt(item, plot, rules["prompts"]["search"], search.get("external_evidence"))
    else:
        issues = [] if node_type == "community" and not item["community_count"] else stage_preflight_issues(STAGES[node_type], context, rules["machine_contracts"][node_type])
        if issues:
            raise ValueError("; ".join(issues))
        with using_rules(rules):
            model_context = {**context, "visual_history": context["visual_history"][-32:]}
            prompt = build_prompt(STAGES[node_type], rules["prompts"][node_type], model_context, feedback, rules["directives"][STAGES[node_type]])
    return StageInput(node_type, prompt, schema, item, context, rules)


def validate_result(stage: StageInput, result: dict, history: list[dict] | None = None) -> list[str]:
    with using_rules(stage.rules):
        if stage.node_type == "search":
            if result.get("plot_payload") != stage.context["plot_payload"]:
                return ["剧情事实与云端输入不一致"]
            market = result.get("market_payload", {})
            issues = c._schema_issues(market, stage.schema)
            if issues:
                raise ValueError("模型结构错误: " + "; ".join(issues))
            return validate_market_packaging_evidence(market, {
                "drama_id": stage.item["video_id"] or stage.item["slot"], "drama_title": stage.item["drama_name"],
                "channel_name": stage.item["channel"], "channel_language": stage.item["language"], "channel_type": stage.item["direction"]})
        if stage.node_type == "merge":
            return []
        schema_issues = c.validate_model_output_schema(STAGES[stage.node_type], result, stage.item, stage.context)
        if schema_issues:
            raise ValueError("模型结构错误: " + "; ".join(schema_issues))
        c.normalize_identity(result, stage.item)
        if stage.node_type == "title":
            c.normalize_title_recommendation_order(result, stage.context)
            c.normalize_title_translation_format(result, stage.context)
        elif stage.node_type == "cover":
            c.normalize_cover_prompt_contract(result, stage.context["cover_rule_contract"])
        elif stage.node_type == "description":
            c.normalize_place_fixed_footer(result, stage.context, stage.item)
        return c.validate_payload(STAGES[stage.node_type], result, stage.item, stage.context, validate_schema=False)
