from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zhiju.config import get_settings
from zhiju.models import (
    Channel,
    ChannelPlaylist,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    CommunityPostAsset,
    Drama,
    DramaAlias,
    DramaCoreTerm,
    MediaAsset,
    OperationPackage,
    OperationTask,
    PackageArtifact,
    PackageCommunityPost,
    PackageCoverVariant,
    PackageCreativeSlot,
    PackageDescription,
    PackageOutputCopyState,
    PackagePlaylistAssignment,
    PackageSimilarityCheck,
    PackageTitle,
    PackageValidationResult,
    ProductionNodeRun,
    ProductionBatch,
    WorkOrder,
    YoutubeVideo,
)
from zhiju.schemas.production import (
    CommunityBatchWrite,
    CoverBatchWrite,
    DescriptionWrite,
    PackageCopyMark,
    TitleBatchWrite,
    ValidationWrite,
    SimilarityCheckWrite,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError, _audit


def _package(session: Session, package_id: str) -> OperationPackage:
    package = session.get(OperationPackage, package_id)
    if package is None:
        raise NotFoundError("运营包不存在")
    return package


def _running_node(session: Session, package: OperationPackage, node_type: str) -> ProductionNodeRun:
    node = session.scalar(
        select(ProductionNodeRun)
        .where(ProductionNodeRun.work_order_id == package.work_order_id, ProductionNodeRun.node_type == node_type)
        .order_by(ProductionNodeRun.attempt_number.desc())
        .limit(1)
        .with_for_update()
    )
    if node is None or node.status != "running":
        raise ConflictError(f"{node_type} 节点未处于运行状态")
    return node


def _current_rows(rows, key):
    latest = {}
    for row in rows:
        latest.setdefault(key(row), row)
    return list(latest.values())


def write_titles(session: Session, package_id: str, payload: TitleBatchWrite) -> list[PackageTitle]:
    package = _package(session, package_id)
    node = _running_node(session, package, "title")
    variants = [item.variant_number for item in payload.titles]
    if sorted(variants) != [1, 2, 3]:
        raise ConflictError("标题必须完整提交 1、2、3 三个候选")
    existing = list(
        session.scalars(
            select(PackageTitle).where(
                PackageTitle.package_id == package.id,
                PackageTitle.generation_number == node.attempt_number,
            )
        )
    )
    if existing:
        raise ConflictError("当前标题节点尝试已经写入结果")
    previous = list(
        session.scalars(
            select(PackageTitle).where(PackageTitle.package_id == package.id, PackageTitle.selected.is_(True))
        )
    )
    for row in previous:
        row.selected = False
        row.status = "superseded"
    rows = [
        PackageTitle(
            package_id=package.id,
            generation_number=node.attempt_number,
            selected=True,
            status="selected",
            **item.model_dump(),
        )
        for item in payload.titles
    ]
    session.add_all(rows)
    if payload.creative_slot is not None:
        creative = session.scalar(select(PackageCreativeSlot).where(PackageCreativeSlot.package_id == package.id))
        if creative is None:
            creative = PackageCreativeSlot(package_id=package.id)
            session.add(creative)
        for field, value in payload.creative_slot.model_dump().items():
            setattr(creative, field, value)
    session.flush()
    _audit(session, "package.titles_written", "operation_package", package.id)
    session.commit()
    return rows


def write_covers(session: Session, package_id: str, payload: CoverBatchWrite) -> list[PackageCoverVariant]:
    package = _package(session, package_id)
    node = _running_node(session, package, "cover")
    title_ids = {item.title_id for item in payload.covers}
    titles = list(session.scalars(select(PackageTitle).where(PackageTitle.id.in_(title_ids))))
    if len(titles) != len(title_ids) or any(title.package_id != package.id for title in titles):
        raise ConflictError("封面关联了不属于当前运营包的标题")
    pairs = {(next(title.variant_number for title in titles if title.id == item.title_id), item.aspect_ratio) for item in payload.covers}
    expected = {(variant, ratio) for variant in (1, 2, 3) for ratio in ("4:5", "16:9")}
    if pairs != expected or len(payload.covers) != 6:
        raise ConflictError("封面必须为三个标题各提交一张 4:5 和一张 16:9")
    asset_ids = {item.asset_id for item in payload.covers if item.asset_id}
    assets = list(session.scalars(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))) if asset_ids else []
    assets_by_id = {asset.id: asset for asset in assets}
    if len(assets) != len(asset_ids) or any(
        asset.operation_package_id != package.id
        or asset.asset_type != "image"
        or asset.asset_role != "thumbnail"
        or asset.status != "ready"
        or asset.deleted_at is not None
        for asset in assets
    ):
        raise ConflictError("封面成品图必须是属于当前运营包的可用缩略图资产")
    for item in payload.covers:
        if not item.asset_id:
            continue
        asset = assets_by_id[item.asset_id]
        ratio = asset.width / asset.height
        expected_ratio = 4 / 5 if item.aspect_ratio == "4:5" else 16 / 9
        if abs(ratio - expected_ratio) > 0.05:
            raise ConflictError(f"封面资产尺寸与{item.aspect_ratio}比例不匹配")
    existing = session.scalar(
        select(PackageCoverVariant.id).where(
            PackageCoverVariant.package_id == package.id,
            PackageCoverVariant.generation_number == node.attempt_number,
        ).limit(1)
    )
    if existing:
        raise ConflictError("当前封面节点尝试已经写入结果")
    previous = list(
        session.scalars(
            select(PackageCoverVariant).where(
                PackageCoverVariant.package_id == package.id,
                PackageCoverVariant.selected.is_(True),
            )
        )
    )
    for row in previous:
        row.selected = False
        row.status = "superseded"
    rows = [
        PackageCoverVariant(
            package_id=package.id,
            generation_number=node.attempt_number,
            **item.model_dump(),
        )
        for item in payload.covers
    ]
    session.add_all(rows)
    session.flush()
    _audit(session, "package.covers_written", "operation_package", package.id)
    session.commit()
    return rows


def write_description(session: Session, package_id: str, payload: DescriptionWrite) -> PackageDescription:
    package = _package(session, package_id)
    node = _running_node(session, package, "description")
    if session.scalar(
        select(PackageDescription.id).where(
            PackageDescription.package_id == package.id,
            PackageDescription.version_number == node.attempt_number,
        )
    ):
        raise ConflictError("当前说明节点尝试已经写入结果")
    previous = list(
        session.scalars(
            select(PackageDescription).where(
                PackageDescription.package_id == package.id,
                PackageDescription.selected.is_(True),
            )
        )
    )
    for row in previous:
        row.selected = False
        row.status = "superseded"
    values = payload.model_dump(exclude={"playlist_id", "playlist_rationale"})
    row = PackageDescription(
        package_id=package.id,
        version_number=node.attempt_number,
        selected=True,
        status="selected",
        **values,
    )
    session.add(row)
    if payload.playlist_id:
        playlist = session.get(ChannelPlaylist, payload.playlist_id)
        if playlist is None or playlist.channel_id != package.channel_id:
            raise ConflictError("播放列表不属于当前频道")
        for assignment in session.scalars(
            select(PackagePlaylistAssignment).where(PackagePlaylistAssignment.package_id == package.id)
        ):
            assignment.status = "rejected"
        assignment = session.scalar(
            select(PackagePlaylistAssignment).where(
                PackagePlaylistAssignment.package_id == package.id,
                PackagePlaylistAssignment.playlist_id == playlist.id,
            )
        )
        if assignment is None:
            assignment = PackagePlaylistAssignment(
                package_id=package.id,
                playlist_id=playlist.id,
                rank_number=1,
            )
            session.add(assignment)
        assignment.rationale = payload.playlist_rationale
        assignment.status = "selected"
    session.flush()
    _audit(session, "package.description_written", "operation_package", package.id)
    session.commit()
    return row


def _community_payload(session: Session, rows: list[PackageCommunityPost]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        asset_ids = list(
            session.scalars(
                select(CommunityPostAsset.asset_id)
                .where(CommunityPostAsset.community_post_id == row.id)
                .order_by(CommunityPostAsset.position_number)
            )
        )
        result.append(
            {
                "id": row.id,
                "package_id": row.package_id,
                "sequence_number": row.sequence_number,
                "version_number": row.version_number,
                "language": row.language,
                "localized_text": row.localized_text,
                "chinese_translation": row.chinese_translation,
                "planned_time": row.planned_time,
                "image_prompt": row.image_prompt,
                "asset_ids": asset_ids,
                "selected": row.selected,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return result


def write_community(session: Session, package_id: str, payload: CommunityBatchWrite) -> list[dict[str, object]]:
    package = _package(session, package_id)
    node = _running_node(session, package, "community")
    work_order = session.get(WorkOrder, package.work_order_id)
    if work_order is None:
        raise NotFoundError("运营包关联工单不存在")
    sequences = [item.sequence_number for item in payload.posts]
    if len(payload.posts) != work_order.community_count or sorted(sequences) != list(range(1, work_order.community_count + 1)):
        raise ConflictError(f"社群文案必须按工单提交 {work_order.community_count} 条连续编号记录")
    if session.scalar(
        select(PackageCommunityPost.id).where(
            PackageCommunityPost.package_id == package.id,
            PackageCommunityPost.version_number == node.attempt_number,
        ).limit(1)
    ):
        raise ConflictError("当前社群节点尝试已经写入结果")
    previous = list(
        session.scalars(
            select(PackageCommunityPost).where(
                PackageCommunityPost.package_id == package.id,
                PackageCommunityPost.selected.is_(True),
            )
        )
    )
    for row in previous:
        row.selected = False
        row.status = "superseded"
    asset_ids = {asset_id for item in payload.posts for asset_id in item.asset_ids}
    assets = list(session.scalars(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))) if asset_ids else []
    if len(assets) != len(asset_ids) or any(
        asset.operation_package_id != package.id
        or asset.asset_type != "image"
        or asset.asset_role != "community_image"
        or asset.status != "ready"
        or asset.deleted_at is not None
        for asset in assets
    ):
        raise ConflictError("社群配图必须是属于当前运营包的可用社群图片资产")
    rows = [
        PackageCommunityPost(
            package_id=package.id,
            version_number=node.attempt_number,
            selected=True,
            status="selected",
            **item.model_dump(exclude={"asset_ids"}),
        )
        for item in payload.posts
    ]
    session.add_all(rows)
    session.flush()
    for item, row in zip(payload.posts, rows, strict=True):
        session.add_all(
            CommunityPostAsset(community_post_id=row.id, asset_id=asset_id, position_number=position)
            for position, asset_id in enumerate(item.asset_ids, start=1)
        )
    _audit(session, "package.community_written", "operation_package", package.id)
    session.commit()
    return _community_payload(session, rows)


def add_validation(session: Session, package_id: str, payload: ValidationWrite) -> PackageValidationResult:
    package = _package(session, package_id)
    previous = list(
        session.scalars(
            select(PackageValidationResult)
            .where(
                PackageValidationResult.package_id == package.id,
                PackageValidationResult.validator_code == payload.validator_code,
                PackageValidationResult.node_type == payload.node_type,
                PackageValidationResult.field_reference == payload.field_reference,
                PackageValidationResult.is_current.is_(True),
            )
            .with_for_update()
        )
    )
    for item in previous:
        item.is_current = False
    row = PackageValidationResult(
        package_id=package.id,
        is_current=True,
        checked_at=datetime.now(timezone.utc),
        **payload.model_dump(),
    )
    session.add(row)
    session.flush()
    _audit(session, "package.validation_written", "operation_package", package.id)
    session.commit()
    return row


def upsert_similarity_check(
    session: Session,
    package_id: str,
    compared_package_id: str,
    payload: SimilarityCheckWrite,
) -> PackageSimilarityCheck:
    package = _package(session, package_id)
    compared = _package(session, compared_package_id)
    if package.id == compared.id:
        raise ConflictError("运营包不能与自身进行相似度比较")
    if not any(
        value is not None
        for value in (
            payload.title_similarity,
            payload.cover_similarity,
            payload.description_similarity,
            payload.creative_similarity,
        )
    ):
        raise ConflictError("相似度检查至少需要一个评分")
    row = session.scalar(
        select(PackageSimilarityCheck)
        .where(
            PackageSimilarityCheck.package_id == package.id,
            PackageSimilarityCheck.compared_package_id == compared.id,
        )
        .with_for_update()
    )
    if row is None:
        row = PackageSimilarityCheck(
            package_id=package.id,
            compared_package_id=compared.id,
        )
        session.add(row)
        action = "package.similarity_check_created"
    else:
        action = "package.similarity_check_updated"
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    row.checked_at = datetime.now(timezone.utc)
    session.flush()
    _audit(session, action, "operation_package", package.id)
    session.commit()
    session.refresh(row)
    return row


def list_similarity_checks(
    session: Session, package_id: str, *, result: str | None = None
) -> list[PackageSimilarityCheck]:
    package = _package(session, package_id)
    statement = select(PackageSimilarityCheck).where(
        PackageSimilarityCheck.package_id == package.id
    )
    if result is not None:
        statement = statement.where(PackageSimilarityCheck.result == result)
    return list(
        session.scalars(
            statement.order_by(
                PackageSimilarityCheck.checked_at.desc(),
                PackageSimilarityCheck.id,
            )
        )
    )


def get_package_outputs(session: Session, package_id: str) -> dict[str, object]:
    package = _package(session, package_id)
    community_rows = list(session.scalars(select(PackageCommunityPost).where(PackageCommunityPost.package_id == package.id).order_by(PackageCommunityPost.version_number.desc(), PackageCommunityPost.sequence_number)))
    return {
        "package": package,
        "creative_slot": session.scalar(select(PackageCreativeSlot).where(PackageCreativeSlot.package_id == package.id)),
        "titles": list(session.scalars(select(PackageTitle).where(PackageTitle.package_id == package.id).order_by(PackageTitle.generation_number.desc(), PackageTitle.variant_number))),
        "covers": list(session.scalars(select(PackageCoverVariant).where(PackageCoverVariant.package_id == package.id).order_by(PackageCoverVariant.generation_number.desc(), PackageCoverVariant.title_id, PackageCoverVariant.aspect_ratio))),
        "descriptions": list(session.scalars(select(PackageDescription).where(PackageDescription.package_id == package.id).order_by(PackageDescription.version_number.desc()))),
        "community_posts": _community_payload(session, community_rows),
        "playlist_assignments": list(session.scalars(select(PackagePlaylistAssignment).where(PackagePlaylistAssignment.package_id == package.id).order_by(PackagePlaylistAssignment.rank_number))),
        "validations": list(session.scalars(select(PackageValidationResult).where(PackageValidationResult.package_id == package.id).order_by(PackageValidationResult.checked_at.desc()))),
        "similarity_checks": list_similarity_checks(session, package.id),
        "artifacts": list(session.scalars(select(PackageArtifact).where(PackageArtifact.package_id == package.id).order_by(PackageArtifact.generation_number.desc(), PackageArtifact.artifact_format))),
    }


def _copy_key(output_type: str, output_id: str) -> str:
    return f"{output_type}:{output_id}"


def _copy_targets(
    titles: list[PackageTitle],
    covers: list[PackageCoverVariant],
    description: PackageDescription | None,
    communities: list[PackageCommunityPost],
) -> set[str]:
    targets = {_copy_key("title", row.id) for row in titles}
    targets.update(_copy_key("cover", row.id) for row in covers if row.creative_prompt)
    if description is not None and description.localized_text:
        targets.add(_copy_key("description", description.id))
    for row in communities:
        if row.localized_text:
            targets.add(_copy_key("community_text", row.id))
        if row.image_prompt:
            targets.add(_copy_key("community_image", row.id))
    return targets


def _copy_progress_payload(package_id: str, targets: set[str], copied: set[str]) -> dict[str, object]:
    current = targets & copied
    copied_count = len(current)
    copy_total = len(targets)
    if copied_count == 0:
        copy_status = "not_started"
    elif copy_total > 0 and copied_count == copy_total:
        copy_status = "completed"
    else:
        copy_status = "in_progress"
    return {
        "package_id": package_id,
        "copy_status": copy_status,
        "copied_keys": sorted(current),
        "copied_count": copied_count,
        "copy_total": copy_total,
    }


def _current_package_copy_targets(session: Session, package_id: str) -> set[str]:
    _package(session, package_id)
    title_rows = list(session.scalars(
        select(PackageTitle)
        .where(PackageTitle.package_id == package_id)
        .order_by(PackageTitle.generation_number.desc(), PackageTitle.variant_number)
    ))
    cover_rows = list(session.scalars(
        select(PackageCoverVariant)
        .where(PackageCoverVariant.package_id == package_id)
        .order_by(PackageCoverVariant.generation_number.desc(), PackageCoverVariant.title_id, PackageCoverVariant.aspect_ratio)
    ))
    description_rows = list(session.scalars(
        select(PackageDescription)
        .where(PackageDescription.package_id == package_id)
        .order_by(PackageDescription.version_number.desc())
    ))
    community_rows = list(session.scalars(
        select(PackageCommunityPost)
        .where(PackageCommunityPost.package_id == package_id)
        .order_by(PackageCommunityPost.version_number.desc(), PackageCommunityPost.sequence_number)
    ))
    return _copy_targets(
        _current_rows(title_rows, lambda row: row.variant_number),
        _current_rows(cover_rows, lambda row: (row.title_id, row.aspect_ratio)),
        next(iter(_current_rows(description_rows, lambda row: row.package_id)), None),
        _current_rows(community_rows, lambda row: row.sequence_number),
    )


def get_package_copy_progress(session: Session, package_id: str) -> dict[str, object]:
    targets = _current_package_copy_targets(session, package_id)
    copied = {
        _copy_key(row.output_type, row.output_id)
        for row in session.scalars(
            select(PackageOutputCopyState).where(PackageOutputCopyState.package_id == package_id)
        )
    }
    return _copy_progress_payload(package_id, targets, copied)


def mark_package_output_copied(session: Session, package_id: str, payload: PackageCopyMark) -> dict[str, object]:
    package = _package(session, package_id)
    if not package.source_complete:
        raise ConflictError(package.source_incomplete_reason or "飞书源数据不完整，暂不可操作")
    targets = _current_package_copy_targets(session, package_id)
    key = _copy_key(payload.output_type, payload.output_id)
    if key not in targets:
        raise ConflictError("复制项不是该运营包的当前可复制产物")
    row = session.scalar(
        select(PackageOutputCopyState).where(
            PackageOutputCopyState.package_id == package_id,
            PackageOutputCopyState.output_type == payload.output_type,
            PackageOutputCopyState.output_id == payload.output_id,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = PackageOutputCopyState(
            package_id=package_id,
            output_type=payload.output_type,
            output_id=payload.output_id,
            copied_at=now,
        )
        session.add(row)
    else:
        row.copied_at = now
    session.flush()
    _audit(session, "package.output_copied", "operation_package", package_id)
    session.commit()
    return get_package_copy_progress(session, package_id)


def list_package_operation_overview(
    session: Session,
    *,
    production_date: date | None = None,
    channel_id: str | None = None,
    package_status: str | None = None,
) -> list[dict[str, object]]:
    latest_version = (
        select(func.max(OperationPackage.version_number))
        .where(OperationPackage.work_order_id == WorkOrder.id)
        .correlate(WorkOrder)
        .scalar_subquery()
    )
    statement = (
        select(OperationPackage, WorkOrder, OperationTask, ProductionBatch, Channel, Drama, ChannelScheduleEntry, YoutubeVideo)
        .join(WorkOrder, WorkOrder.id == OperationPackage.work_order_id)
        .join(OperationTask, OperationTask.id == WorkOrder.task_id)
        .outerjoin(ProductionBatch, ProductionBatch.id == OperationPackage.batch_id)
        .join(Channel, Channel.id == OperationPackage.channel_id)
        .join(Drama, Drama.id == OperationPackage.drama_id)
        .outerjoin(ChannelScheduleEntry, ChannelScheduleEntry.id == OperationPackage.schedule_id)
        .outerjoin(YoutubeVideo, YoutubeVideo.operation_package_id == OperationPackage.id)
        .where(OperationPackage.version_number == latest_version)
    )
    if production_date:
        statement = statement.where(WorkOrder.production_date == production_date)
    if channel_id:
        statement = statement.where(OperationPackage.channel_id == channel_id)
    if package_status:
        statement = statement.where(OperationPackage.status == package_status)
    rows = list(session.execute(statement.order_by(
        WorkOrder.production_date.desc(),
        OperationTask.source_row_number.is_(None),
        OperationTask.source_row_number.asc(),
        WorkOrder.created_at.asc(),
    )))
    package_ids = [package.id for package, *_ in rows]
    if not package_ids:
        return []

    title_rows = list(session.scalars(
        select(PackageTitle)
        .where(PackageTitle.package_id.in_(package_ids))
        .order_by(PackageTitle.generation_number.desc(), PackageTitle.variant_number)
    ))
    cover_rows = list(session.scalars(
        select(PackageCoverVariant)
        .where(PackageCoverVariant.package_id.in_(package_ids))
        .order_by(PackageCoverVariant.generation_number.desc(), PackageCoverVariant.title_id, PackageCoverVariant.aspect_ratio)
    ))
    description_rows = list(session.scalars(
        select(PackageDescription)
        .where(PackageDescription.package_id.in_(package_ids))
        .order_by(PackageDescription.version_number.desc())
    ))
    community_rows = list(session.scalars(
        select(PackageCommunityPost)
        .where(PackageCommunityPost.package_id.in_(package_ids))
        .order_by(PackageCommunityPost.version_number.desc(), PackageCommunityPost.sequence_number)
    ))
    playlist_rows = list(session.execute(
        select(PackagePlaylistAssignment, ChannelPlaylist)
        .join(ChannelPlaylist, ChannelPlaylist.id == PackagePlaylistAssignment.playlist_id)
        .where(PackagePlaylistAssignment.package_id.in_(package_ids))
        .order_by(PackagePlaylistAssignment.rank_number)
    ))
    copy_rows = list(session.scalars(
        select(PackageOutputCopyState).where(PackageOutputCopyState.package_id.in_(package_ids))
    ))

    titles: dict[str, list[PackageTitle]] = defaultdict(list)
    for title in _current_rows(title_rows, lambda row: (row.package_id, row.variant_number)):
        titles[title.package_id].append(title)
    covers: dict[str, list[PackageCoverVariant]] = defaultdict(list)
    for cover in _current_rows(cover_rows, lambda row: (row.package_id, row.title_id, row.aspect_ratio)):
        covers[cover.package_id].append(cover)
    descriptions = {
        row.package_id: row
        for row in _current_rows(description_rows, lambda item: item.package_id)
    }
    communities: dict[str, list[PackageCommunityPost]] = defaultdict(list)
    for post in _current_rows(community_rows, lambda row: (row.package_id, row.sequence_number)):
        communities[post.package_id].append(post)
    playlists: dict[str, tuple[PackagePlaylistAssignment, ChannelPlaylist]] = {}
    for assignment, playlist in playlist_rows:
        current = playlists.get(assignment.package_id)
        if current is None or assignment.status == "selected":
            playlists[assignment.package_id] = (assignment, playlist)
    copied_by_package: dict[str, set[str]] = defaultdict(set)
    for row in copy_rows:
        copied_by_package[row.package_id].add(_copy_key(row.output_type, row.output_id))

    result = []
    for package, work_order, task, batch, channel, drama, schedule, video in rows:
        playlist_pair = playlists.get(package.id)
        playlist = playlist_pair[1] if playlist_pair else None
        package_titles = sorted(titles.get(package.id, []), key=lambda item: item.variant_number)
        package_covers = covers.get(package.id, [])
        package_description = descriptions.get(package.id)
        package_communities = sorted(communities.get(package.id, []), key=lambda item: item.sequence_number)
        copy_progress = _copy_progress_payload(
            package.id,
            _copy_targets(package_titles, package_covers, package_description, package_communities),
            copied_by_package.get(package.id, set()),
        )
        publish_slot = session.get(ChannelPublishSlot, task.publish_slot_id) if task.publish_slot_id else None
        planned_local_time = (
            schedule.planned_local_time
            if schedule
            else datetime.combine(task.target_publish_date, publish_slot.local_time)
            if publish_slot
            else None
        )
        result.append({
            "package_id": package.id,
            "work_order_id": work_order.id,
            "package_version": package.version_number,
            "package_status": package.status,
            "source_complete": package.source_complete,
            "source_incomplete_reason": package.source_incomplete_reason,
            "work_order_status": work_order.status,
            "production_date": work_order.production_date,
            "target_publish_date": work_order.target_publish_date,
            "planned_local_time": planned_local_time,
            "channel_id": channel.id,
            "channel_name": channel.operational_name or channel.original_name,
            "channel_original_name": channel.original_name,
            "drama_id": drama.id,
            "drama_number": drama.drama_number,
            "business_drama_id": task.source_video_id or str(drama.drama_number),
            "source_row_number": task.source_row_number,
            "drama_code": drama.drama_code,
            "chinese_title": drama.chinese_title,
            "drama_resource_url": drama.baidu_cloud_url,
            "youtube_video_id": task.source_video_id or (video.youtube_video_id if video else None),
            "video_url": task.source_video_url or (video.url if video else None),
            "batch_number": batch.batch_number if batch else None,
            "community_count": work_order.community_count,
            "playlist_id": playlist.id if playlist else None,
            "playlist_name": playlist.local_name if playlist else None,
            "playlist_url": playlist.url if playlist else None,
            "titles": package_titles,
            "covers": package_covers,
            "description": package_description,
            "community_posts": package_communities,
            **copy_progress,
        })
    return result


def validate_node_output(session: Session, node: ProductionNodeRun) -> None:
    package = _package(session, node.package_id)
    if node.node_type == "search":
        drama = session.get(Drama, package.drama_id)
        if drama is None or not drama.content_summary:
            raise ConflictError("搜索节点未将剧情资料写入本地剧库")
    elif node.node_type == "title":
        variants = set(session.scalars(select(PackageTitle.variant_number).where(PackageTitle.package_id == package.id, PackageTitle.generation_number == node.attempt_number)))
        if variants != {1, 2, 3}:
            raise ConflictError("标题节点缺少本次尝试的三个标题结果")
    elif node.node_type == "cover":
        count = len(list(session.scalars(select(PackageCoverVariant.id).where(PackageCoverVariant.package_id == package.id, PackageCoverVariant.generation_number == node.attempt_number))))
        if count != 6:
            raise ConflictError("封面节点缺少本次尝试的六个封面结果")
    elif node.node_type == "description":
        if not session.scalar(select(PackageDescription.id).where(PackageDescription.package_id == package.id, PackageDescription.version_number == node.attempt_number)):
            raise ConflictError("说明节点缺少本次尝试的说明结果")
    elif node.node_type == "community":
        work_order = session.get(WorkOrder, package.work_order_id)
        count = len(list(session.scalars(select(PackageCommunityPost.id).where(PackageCommunityPost.package_id == package.id, PackageCommunityPost.version_number == node.attempt_number))))
        if work_order is None or count != work_order.community_count:
            raise ConflictError("社群节点结果数量与工单不一致")


def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _selected_snapshot(session: Session, package: OperationPackage) -> dict[str, object]:
    work_order = session.get(WorkOrder, package.work_order_id)
    channel = session.get(Channel, package.channel_id)
    drama = session.get(Drama, package.drama_id)
    schedule = session.get(ChannelScheduleEntry, package.schedule_id) if package.schedule_id else None
    if work_order is None or channel is None or drama is None:
        raise ConflictError("运营包基础关联数据不完整")
    if session.scalar(
        select(PackageSimilarityCheck.id)
        .where(
            PackageSimilarityCheck.package_id == package.id,
            PackageSimilarityCheck.result == "fail",
        )
        .limit(1)
    ):
        raise ConflictError("运营包仍有未通过的历史相似度检查")
    titles = list(session.scalars(select(PackageTitle).where(PackageTitle.package_id == package.id, PackageTitle.selected.is_(True)).order_by(PackageTitle.variant_number)))
    if {row.variant_number for row in titles} != {1, 2, 3}:
        raise ConflictError("运营包缺少三个当前标题")
    all_covers = list(
        session.execute(
            select(PackageCoverVariant, PackageTitle.variant_number)
            .join(PackageTitle, PackageTitle.id == PackageCoverVariant.title_id)
            .where(PackageCoverVariant.package_id == package.id, PackageCoverVariant.selected.is_(True))
            .order_by(PackageCoverVariant.generation_number.desc())
        )
    )
    cover_latest = _current_rows(all_covers, lambda pair: (pair[1], pair[0].aspect_ratio))
    if {(variant, cover.aspect_ratio) for cover, variant in cover_latest} != {(variant, ratio) for variant in (1, 2, 3) for ratio in ("4:5", "16:9")}:
        raise ConflictError("运营包缺少标题与 4:5、16:9 封面的完整对应关系")
    description = session.scalar(select(PackageDescription).where(PackageDescription.package_id == package.id, PackageDescription.selected.is_(True)).order_by(PackageDescription.version_number.desc()))
    if description is None:
        raise ConflictError("运营包缺少当前说明")
    communities = list(session.scalars(select(PackageCommunityPost).where(PackageCommunityPost.package_id == package.id, PackageCommunityPost.selected.is_(True)).order_by(PackageCommunityPost.sequence_number)))
    if len(communities) != work_order.community_count:
        raise ConflictError("运营包社群文案数量与工单不一致")
    if session.scalar(
        select(PackageValidationResult.id)
        .where(
            PackageValidationResult.package_id == package.id,
            PackageValidationResult.is_current.is_(True),
            PackageValidationResult.result == "fail",
        )
        .limit(1)
    ):
        raise ConflictError("运营包仍有未解决的失败检测项")
    playlist_assignment = session.scalar(select(PackagePlaylistAssignment).where(PackagePlaylistAssignment.package_id == package.id, PackagePlaylistAssignment.status == "selected"))
    playlist = session.get(ChannelPlaylist, playlist_assignment.playlist_id) if playlist_assignment else None
    creative = session.scalar(select(PackageCreativeSlot).where(PackageCreativeSlot.package_id == package.id))
    aliases = list(session.scalars(select(DramaAlias).where(DramaAlias.drama_id == drama.id).order_by(DramaAlias.alias)))
    terms = list(session.scalars(select(DramaCoreTerm).where(DramaCoreTerm.drama_id == drama.id).order_by(DramaCoreTerm.term_type, DramaCoreTerm.term)))
    cover_asset_ids = {cover.asset_id for cover, _ in cover_latest if cover.asset_id}
    assets = {asset.id: asset for asset in session.scalars(select(MediaAsset).where(MediaAsset.id.in_(cover_asset_ids)))} if cover_asset_ids else {}
    title_data = []
    for title in titles:
        covers = []
        for cover, variant in cover_latest:
            if variant != title.variant_number:
                continue
            asset = assets.get(cover.asset_id)
            covers.append({
                "id": cover.id,
                "aspect_ratio": cover.aspect_ratio,
                "creative_prompt": cover.creative_prompt,
                "asset_id": cover.asset_id,
                "asset_storage_key": asset.storage_key if asset else None,
                "status": cover.status,
            })
        title_data.append({
            "id": title.id,
            "variant_number": title.variant_number,
            "localized_title": title.localized_title,
            "chinese_translation": title.chinese_translation,
            "core_phrase": title.core_phrase,
            "score": title.score,
            "covers": sorted(covers, key=lambda row: row["aspect_ratio"]),
        })
    return {
        "package": {"id": package.id, "version_number": package.version_number},
        "work_order": {"id": work_order.id, "production_date": work_order.production_date, "target_publish_date": work_order.target_publish_date},
        "channel": {"id": channel.id, "youtube_channel_id": channel.youtube_channel_id, "name": channel.original_name, "operational_name": channel.operational_name, "language": channel.default_language, "timezone": channel.timezone},
        "drama": {"id": drama.id, "drama_code": drama.drama_code, "chinese_title": drama.chinese_title, "aliases": [row.alias for row in aliases], "content_summary": drama.content_summary, "plot_archive": drama.plot_archive, "plot_pattern": drama.plot_pattern, "core_personas": drama.core_personas, "core_terms": [{"type": row.term_type, "term": row.term, "weight": row.weight} for row in terms]},
        "schedule": {"id": schedule.id, "publish_date": schedule.publish_date, "planned_local_time": schedule.planned_local_time, "planned_beijing_time": schedule.planned_beijing_time, "planned_utc_time": schedule.planned_utc_time} if schedule else None,
        "creative_slot": {column: getattr(creative, column) for column in ("character_focus", "plot_focus", "emotion", "title_hook", "thumbnail_scene", "thumbnail_action", "thumbnail_layout", "description_angle", "community_angle")} if creative else None,
        "titles": title_data,
        "description": {"language": description.language, "localized_text": description.localized_text, "chinese_translation": description.chinese_translation, "pinned_comment": description.pinned_comment},
        "playlist": {"id": playlist.id, "local_name": playlist.local_name, "chinese_name": playlist.chinese_name, "url": playlist.url} if playlist else None,
        "community_posts": [
            {
                "sequence_number": row.sequence_number,
                "language": row.language,
                "localized_text": row.localized_text,
                "chinese_translation": row.chinese_translation,
                "planned_time": row.planned_time,
                "image_prompt": row.image_prompt,
                "assets": [
                    {"id": asset.id, "storage_key": asset.storage_key, "sha256": asset.sha256}
                    for asset in session.scalars(
                        select(MediaAsset)
                        .join(CommunityPostAsset, CommunityPostAsset.asset_id == MediaAsset.id)
                        .where(CommunityPostAsset.community_post_id == row.id)
                        .order_by(CommunityPostAsset.position_number)
                    )
                ],
            }
            for row in communities
        ],
    }


def _render_markdown(snapshot: dict[str, object]) -> str:
    channel = snapshot["channel"]
    drama = snapshot["drama"]
    lines = [
        f"# {drama['chinese_title']} 运营包",
        "",
        f"- 运营包 ID: {snapshot['package']['id']}",
        f"- 工单 ID: {snapshot['work_order']['id']}",
        f"- 频道: {channel['operational_name'] or channel['name']}",
        f"- 剧库 ID: {drama['drama_code']}",
        f"- 目标发布日期: {snapshot['work_order']['target_publish_date']}",
        "",
        "## 剧情资料",
        "",
        drama.get("content_summary") or "",
        "",
        "## 标题与封面",
    ]
    for title in snapshot["titles"]:
        lines.extend(["", f"### 标题 {title['variant_number']}", "", title["localized_title"], "", f"中文翻译: {title.get('chinese_translation') or ''}", f"核心词: {title.get('core_phrase') or ''}"])
        for cover in title["covers"]:
            lines.extend(["", f"#### 封面 {cover['aspect_ratio']}", "", cover["creative_prompt"], "", f"资产: {cover.get('asset_storage_key') or '尚未关联成品图'}"])
    description = snapshot["description"]
    lines.extend(["", "## 说明", "", description["localized_text"], "", "### 说明中文翻译", "", description.get("chinese_translation") or "", "", "### 置顶评论", "", description.get("pinned_comment") or ""])
    playlist = snapshot.get("playlist")
    lines.extend(["", "## 播放列表", "", playlist["local_name"] if playlist else "未指定"])
    lines.extend(["", "## 社群", ""])
    for post in snapshot["community_posts"]:
        lines.extend([f"### 社群 {post['sequence_number']}", "", post["localized_text"], "", f"中文翻译: {post.get('chinese_translation') or ''}", "", f"配图提示词: {post.get('image_prompt') or ''}", ""])
    return "\n".join(lines).rstrip() + "\n"


def merge_package(session: Session, package_id: str) -> dict[str, object]:
    package = _package(session, package_id)
    node = _running_node(session, package, "merge")
    snapshot = _selected_snapshot(session, package)
    generation = node.attempt_number
    root = Path(get_settings().artifact_root)
    relative_dir = Path(package.id) / f"generation-{generation}"
    output_dir = root / relative_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    json_bytes = json.dumps(snapshot, ensure_ascii=False, indent=2, default=_json_safe).encode("utf-8")
    md_bytes = _render_markdown(snapshot).encode("utf-8")
    artifacts = []
    for artifact_format, content in (("json", json_bytes), ("md", md_bytes)):
        final_path = output_dir / f"package.{artifact_format}"
        temporary_path = final_path.with_suffix(final_path.suffix + ".tmp")
        temporary_path.write_bytes(content)
        temporary_path.replace(final_path)
        previous = list(session.scalars(select(PackageArtifact).where(PackageArtifact.package_id == package.id, PackageArtifact.artifact_format == artifact_format, PackageArtifact.status == "ready")))
        for row in previous:
            row.status = "superseded"
        artifact = PackageArtifact(
            package_id=package.id,
            artifact_format=artifact_format,
            generation_number=generation,
            storage_provider="local",
            storage_key=str(relative_dir / final_path.name),
            sha256=hashlib.sha256(content).hexdigest(),
            status="ready",
            ready_at=datetime.now(timezone.utc),
        )
        session.add(artifact)
        artifacts.append(artifact)
    session.flush()
    _audit(session, "package.artifacts_merged", "operation_package", package.id)
    from zhiju.services.production import finish_node

    detail = finish_node(session, package.work_order_id, "merge", success=True, allow_merge=True)
    return {"detail": detail, "artifacts": artifacts}
