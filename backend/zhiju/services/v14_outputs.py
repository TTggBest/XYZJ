"""Project validated V14 JSON onto existing outputs, inside the caller transaction."""
from sqlalchemy import select

from zhiju.models import PackageTitle, ChannelPlaylist
from zhiju.schemas.production import TitleBatchWrite, CoverBatchWrite, DescriptionWrite, CommunityBatchWrite
from zhiju.services import package_outputs as out, production
from zhiju.services.identity import ConflictError
from zhiju.v14_runtime.contract import build_stage_input, validate_result
from zhiju.v14_runtime.canonical import title_rows, cover_rows, first_result


def apply_outputs(session, run, attempt, result):
    from zhiju.services.v14_runs import envelope
    try:
        stage = build_stage_input(envelope(session, run), attempt.node_type)
        issues = validate_result(stage, result)
    except (ValueError, KeyError, TypeError) as exc:
        raise ConflictError(f"V14 结构或输入不完整: {exc}") from exc
    if issues:
        raise ConflictError("V14 验收失败: " + "; ".join(issues))
    node = production._latest_node(session, run.work_order_id, attempt.node_type, lock=True)
    if node.status == "queued":
        production.start_node(session, run.work_order_id, attempt.node_type, run.host_id, commit=False)
    elif node.status != "running" or node.worker_key != run.host_id:
        raise ConflictError("生产节点不属于当前 V14 执行")
    pid = run.package_id
    language = stage.item["language"]
    if attempt.node_type == "title":
        out.write_titles(session, pid, TitleBatchWrite(titles=[{
            "variant_number": r["index"], "localized_title": r["title"], "chinese_translation": r["translation"],
            "score": r["recommendation_score"]} for r in title_rows(result)]), commit=False)
    elif attempt.node_type == "cover":
        titles = {t.variant_number: t.id for t in session.scalars(select(PackageTitle).where(PackageTitle.package_id == pid, PackageTitle.selected.is_(True)))}
        out.write_covers(session, pid, CoverBatchWrite(covers=[{
            "title_id": titles[r["title_index"]], "aspect_ratio": ratio, "creative_prompt": r[key]}
            for r in cover_rows(result) for ratio, key in (("4:5", "prompt_4_5"), ("16:9", "prompt_16_9"))]), commit=False)
    elif attempt.node_type == "description":
        r = first_result(result)
        playlist = session.scalar(select(ChannelPlaylist).where(ChannelPlaylist.channel_id == run.input_snapshot["channel_id"], ChannelPlaylist.url == r["url"]))
        out.write_description(session, pid, DescriptionWrite(language=language, localized_text=r["description"],
            chinese_translation=r["translation"], playlist_id=playlist.id if playlist else None), commit=False)
    elif attempt.node_type == "community":
        out.write_community(session, pid, CommunityBatchWrite(posts=[{
            "sequence_number": r["plan_index"], "language": language, "localized_text": r["copy"],
            "chinese_translation": r["copy_translation"], "image_prompt": r["image_prompt_1x1"]}
            for r in result["results"]]), commit=False)
    if attempt.node_type == "merge":
        out.merge_package(session, pid, commit=False)
    else:
        production.finish_node(session, run.work_order_id, attempt.node_type, success=True, commit=False)
