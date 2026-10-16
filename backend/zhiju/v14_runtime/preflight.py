"""V14 pre-model contract checks, extracted from the existing controller."""
from typing import Any
from .canonical import first_result
from .channel import channel_generation_spec_sections
SystemStageError = ValueError
CONTENT_STAGES = ("xy-title", "xy-cover", "xy-place", "xy-post")

def stage_preflight_issues(
    stage: str,
    context: dict[str, Any],
    machine_contract: dict[str, Any],
) -> list[str]:
    """Reject deterministic contract/context faults before spending a model call."""
    issues: list[str] = []
    task = context.get("task") if isinstance(context.get("task"), dict) else {}
    if int(task.get("workflow_contract_version") or 1) < 2:
        return []
    if stage in CONTENT_STAGES and not machine_contract:
        issues.append(f"preflight_{stage}_frozen_machine_contract_missing")
    if stage == "xy-title":
        try:
            channel_generation_spec_sections(str(context.get("channel_snapshot") or ""))
        except SystemStageError as exc:
            issues.append(str(exc))
        market = context.get("market_packaging") if isinstance(context.get("market_packaging"), dict) else {}
        final_angles = market.get("final_angles") if isinstance(market.get("final_angles"), list) else []
        if [str(row.get("angle_id") or "") for row in final_angles if isinstance(row, dict)] != ["A", "B", "C"]:
            issues.append("preflight_market_packaging_final_angles_missing")
    theme = context.get("channel_theme_contract") if isinstance(context.get("channel_theme_contract"), dict) else {}
    if not str(theme.get("channel_direction") or "").strip():
        issues.append("preflight_channel_direction_missing")
    plot = context.get("plot_payload") if isinstance(context.get("plot_payload"), dict) else {}
    if not plot.get("results"):
        issues.append("preflight_plot_payload_missing")
    if stage in {"xy-cover", "xy-place", "xy-post"}:
        title = first_result(context.get("title_payload") if isinstance(context.get("title_payload"), dict) else {})
        if not isinstance(title.get("packaging_brief"), dict):
            issues.append("preflight_packaging_brief_missing")
    if stage == "xy-post":
        footer = context.get("community_footer_cta") if isinstance(context.get("community_footer_cta"), dict) else {}
        if not all(str(footer.get(key) or "").strip() for key in (
            "full_video_cta", "subscribe_cta", "share_cta", "layout_style"
        )):
            issues.append("preflight_community_fixed_cta_incomplete")
    if stage == "xy-place":
        description_contract = machine_contract.get("description_contract")
        description_contract = description_contract if isinstance(description_contract, dict) else {}
        playlists = context.get("playlists")
        if not isinstance(playlists, list) or not playlists:
            issues.append("preflight_channel_registered_playlist_missing")
        if description_contract.get("channel_hashtag_whitelist_required"):
            evidence = context.get("channel_hashtag_whitelist")
            candidates = evidence.get("additional_candidates") if isinstance(evidence, dict) else None
            if not candidates:
                issues.append("preflight_channel_hashtag_whitelist_missing")
    return issues
