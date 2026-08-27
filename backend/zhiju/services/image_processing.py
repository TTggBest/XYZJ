from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from zhiju.config import get_settings
from zhiju.models import (
    Channel,
    ChannelLogoProfile,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    Drama,
    ImageProcessingItem,
    ImageProcessingRun,
    ImageWorkspaceSetting,
    OperationPackage,
    OperationTask,
    ProductionBatch,
    WorkOrder,
)
from zhiju.schemas.image_processing import (
    ChannelLogoProfileRead,
    ImageProcessingBatchRead,
    ImageProcessingItemRead,
    ImageProcessingRunRead,
    ImageWorkspaceRead,
)


WORKSPACE_SETTING_ID = "image-workspace"
PERSISTENT_DIR = "系统素材"
OUTPUT_DIR = "用户产物"
LOGO_ROLES = {"02_标题1_16x9", "04_标题2_16x9", "06_标题3_16x9"}
ROLE_SUFFIXES = {
    "1_4_5": "01_标题1_4x5",
    "1": "02_标题1_16x9",
    "2_4_5": "03_标题2_4x5",
    "2": "04_标题2_16x9",
    "3_4_5": "05_标题3_4x5",
    "3": "06_标题3_16x9",
    "": "07_社群1_1x1",
    "_2": "08_社群2_1x1",
}
FULL_ROLE_NAMES = {
    "01_title1_4x5": "01_标题1_4x5",
    "02_title1_16x9": "02_标题1_16x9",
    "03_title2_4x5": "03_标题2_4x5",
    "04_title2_16x9": "04_标题2_16x9",
    "05_title3_4x5": "05_标题3_4x5",
    "06_title3_16x9": "06_标题3_16x9",
    "07_community1_1x1": "07_社群1_1x1",
    "08_community2_1x1": "08_社群2_1x1",
    **{value: value for value in ROLE_SUFFIXES.values()},
}


@dataclass(frozen=True)
class FilenameMatch:
    identifier: str | None
    role: str | None
    match_status: str
    method: str | None = None


@dataclass(frozen=True)
class PackageContext:
    package_id: str
    channel_id: str
    channel_name: str
    language: str
    drama_id: str
    drama_title: str
    drama_code: str
    drama_number: int
    video_id: str | None
    schedule_id: str | None
    target_publish_date: str
    slot_type: str | None
    slot_number: int | None

    @property
    def identifiers(self) -> tuple[str, ...]:
        values = [self.video_id, self.drama_code, str(self.drama_number)]
        return tuple(value for value in values if value)


def resolve_workspace_root(root_path: str, shared_root: Path | None) -> Path:
    configured = Path(root_path).expanduser()
    if configured.is_absolute():
        return configured.resolve()
    if shared_root is None:
        raise ValueError("相对图片目录需要当前设备配置 ZHJ_SHARED_ROOT")
    return (shared_root.expanduser() / configured).resolve()


def _workspace_paths(setting: ImageWorkspaceSetting) -> tuple[Path, Path, Path]:
    root = resolve_workspace_root(setting.root_path, get_settings().shared_root)
    return root, root / setting.persistent_dir_name, root / setting.output_dir_name


def _ensure_workspace(setting: ImageWorkspaceSetting) -> tuple[Path, Path, Path]:
    paths = _workspace_paths(setting)
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _workspace_setting(session: Session) -> ImageWorkspaceSetting:
    setting = session.get(ImageWorkspaceSetting, WORKSPACE_SETTING_ID)
    if setting is None:
        raise ValueError("请先在设置页配置图片根目录")
    return setting


def _workspace_read(setting: ImageWorkspaceSetting) -> ImageWorkspaceRead:
    root, persistent, output = _workspace_paths(setting)
    return ImageWorkspaceRead(
        id=setting.id,
        root_path=setting.root_path,
        resolved_root=str(root),
        persistent_root=str(persistent),
        output_root=str(output),
        updated_at=setting.updated_at,
    )


def get_workspace(session: Session) -> ImageWorkspaceRead | None:
    setting = session.get(ImageWorkspaceSetting, WORKSPACE_SETTING_ID)
    return _workspace_read(setting) if setting else None


def save_workspace(session: Session, root_path: str) -> ImageWorkspaceRead:
    root_path = root_path.strip()
    setting = session.get(ImageWorkspaceSetting, WORKSPACE_SETTING_ID)
    if setting is None:
        setting = ImageWorkspaceSetting(
            id=WORKSPACE_SETTING_ID,
            root_path=root_path,
            persistent_dir_name=PERSISTENT_DIR,
            output_dir_name=OUTPUT_DIR,
        )
        session.add(setting)
    else:
        setting.root_path = root_path
    _ensure_workspace(setting)
    session.commit()
    session.refresh(setting)
    return _workspace_read(setting)


def _content_bbox(image: Image.Image, start_x: int, end_x: int) -> tuple[int, int, int, int] | None:
    region = image.convert("RGB").crop((start_x, 0, end_x, image.height))
    white = Image.new("RGB", region.size, "white")
    diff = ImageChops.difference(region, white).convert("L").point(lambda value: 255 if value > 18 else 0)
    bbox = diff.getbbox()
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    return left + start_x, top, right + start_x, bottom


def _normalized_region(bbox: tuple[int, int, int, int], width: int, height: int) -> dict[str, float]:
    left, top, right, bottom = bbox
    return {
        "x": round(left / width, 6),
        "y": round(top / height, 6),
        "width": round((right - left) / width, 6),
        "height": round((bottom - top) / height, 6),
    }


def calibrate_template(template_path: Path) -> dict[str, object]:
    with Image.open(template_path) as source:
        image = source.convert("RGB")
    midpoint = image.width // 2
    left = _content_bbox(image, 0, midpoint)
    right = _content_bbox(image, midpoint, image.width)
    if left is None or right is None:
        raise ValueError("模板必须在左右两侧都包含可识别的 Logo 区域")
    return {
        "version": 1,
        "calibrated": True,
        "canvas": {"width": image.width, "height": image.height},
        "left_logo": _normalized_region(left, image.width, image.height),
        "right_logo": _normalized_region(right, image.width, image.height),
    }


def classify_image_filename(filename: str, identifiers: Iterable[str]) -> FilenameMatch:
    stem = Path(filename).stem
    matches: list[tuple[str, str, str]] = []
    for identifier in sorted({str(value) for value in identifiers if value}, key=len, reverse=True):
        if not stem.startswith(identifier):
            continue
        suffix = stem[len(identifier):]
        full_suffix = suffix[1:] if suffix.startswith("_") else suffix
        if full_suffix in FULL_ROLE_NAMES:
            matches.append((identifier, FULL_ROLE_NAMES[full_suffix], "full_task_id"))
        elif suffix in ROLE_SUFFIXES:
            matches.append((identifier, ROLE_SUFFIXES[suffix], "compact_name"))
    unique = {(identifier, role, method) for identifier, role, method in matches}
    if len(unique) == 1:
        identifier, role, method = unique.pop()
        return FilenameMatch(identifier, role, "matched", method)
    if len(unique) > 1:
        return FilenameMatch(None, None, "ambiguous")
    return FilenameMatch(None, None, "unmatched")


def _safe_segment(value: object, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", str(value or "").strip())
    return text.strip(". ") or fallback


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _validate_image(data: bytes, label: str) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except Exception as exc:
        raise ValueError(f"{label}不是可读取的图片") from exc


def save_channel_logo_profile(
    session: Session,
    channel_id: str,
    left_filename: str,
    left_data: bytes,
    right_filename: str,
    right_data: bytes,
    template_filename: str,
    template_data: bytes,
) -> ChannelLogoProfileRead:
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise ValueError("频道不存在")
    setting = _workspace_setting(session)
    root, persistent, _ = _ensure_workspace(setting)
    logo_dir = persistent / "频道" / _safe_segment(channel.youtube_channel_id, channel.id) / "logo"
    left_path = logo_dir / "llogo" / "left-logo.png"
    right_path = logo_dir / "rlogo" / "right-logo.png"
    template_path = logo_dir / "tem.jpg"
    for path in (left_path, right_path, template_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    left_image = _validate_image(left_data, left_filename).convert("RGBA")
    right_image = _validate_image(right_data, right_filename).convert("RGBA")
    template_image = _validate_image(template_data, template_filename).convert("RGB")
    left_image.save(left_path)
    right_image.save(right_path)
    template_image.save(template_path, quality=100)
    config = calibrate_template(template_path)
    config.update({
        "left_logo_file": _relative(root, left_path),
        "right_logo_file": _relative(root, right_path),
        "template_file": _relative(root, template_path),
    })
    config_path = logo_dir / "logo_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = logo_dir / "logo校准报告.md"
    report_path.write_text(
        f"# Logo 校准报告\n\n- 频道：{channel.operational_name or channel.original_name}\n"
        f"- 画布：{config['canvas']['width']}x{config['canvas']['height']}\n"
        f"- 左 Logo：{json.dumps(config['left_logo'], ensure_ascii=False)}\n"
        f"- 右 Logo：{json.dumps(config['right_logo'], ensure_ascii=False)}\n",
        encoding="utf-8",
    )

    profile = session.scalar(select(ChannelLogoProfile).where(ChannelLogoProfile.channel_id == channel.id))
    now = datetime.now(timezone.utc)
    values = {
        "status": "calibrated",
        "left_logo_path": _relative(root, left_path),
        "right_logo_path": _relative(root, right_path),
        "template_path": _relative(root, template_path),
        "config_path": _relative(root, config_path),
        "canvas_width": config["canvas"]["width"],
        "canvas_height": config["canvas"]["height"],
        "calibrated_at": now,
    }
    if profile is None:
        profile = ChannelLogoProfile(channel_id=channel.id, **values)
        session.add(profile)
    else:
        for key, value in values.items():
            setattr(profile, key, value)
    session.commit()
    session.refresh(profile)
    return _profile_read(profile, channel)


def _profile_read(profile: ChannelLogoProfile, channel: Channel) -> ChannelLogoProfileRead:
    return ChannelLogoProfileRead(
        id=profile.id,
        channel_id=profile.channel_id,
        channel_name=channel.operational_name or channel.original_name,
        status=profile.status,
        left_logo_path=profile.left_logo_path,
        right_logo_path=profile.right_logo_path,
        template_path=profile.template_path,
        config_path=profile.config_path,
        canvas_width=profile.canvas_width,
        canvas_height=profile.canvas_height,
        calibrated_at=profile.calibrated_at,
        updated_at=profile.updated_at,
    )


def list_channel_logo_profiles(session: Session) -> list[ChannelLogoProfileRead]:
    rows = session.execute(
        select(ChannelLogoProfile, Channel)
        .join(Channel, Channel.id == ChannelLogoProfile.channel_id)
        .order_by(Channel.country_name_zh, Channel.display_order, Channel.original_name)
    ).all()
    return [_profile_read(profile, channel) for profile, channel in rows]


def list_processing_batches(session: Session) -> list[ImageProcessingBatchRead]:
    rows = session.execute(
        select(ProductionBatch, func.count(OperationPackage.id))
        .outerjoin(OperationPackage, OperationPackage.batch_id == ProductionBatch.id)
        .group_by(ProductionBatch.id)
        .order_by(ProductionBatch.production_date.desc(), ProductionBatch.created_at.desc())
    ).all()
    return [
        ImageProcessingBatchRead(
            id=batch.id,
            batch_number=batch.batch_number,
            production_date=batch.production_date,
            status=batch.status,
            package_count=count,
        )
        for batch, count in rows
    ]


def _package_contexts(session: Session, batch_id: str) -> list[PackageContext]:
    rows = session.execute(
        select(
            OperationPackage,
            WorkOrder,
            OperationTask,
            Channel,
            Drama,
            ChannelScheduleEntry,
            ChannelPublishSlot,
        )
        .join(WorkOrder, WorkOrder.id == OperationPackage.work_order_id)
        .join(OperationTask, OperationTask.id == WorkOrder.task_id)
        .join(Channel, Channel.id == OperationPackage.channel_id)
        .join(Drama, Drama.id == OperationPackage.drama_id)
        .outerjoin(ChannelScheduleEntry, ChannelScheduleEntry.id == OperationPackage.schedule_id)
        .outerjoin(ChannelPublishSlot, ChannelPublishSlot.id == WorkOrder.publish_slot_id)
        .where(or_(OperationPackage.batch_id == batch_id, WorkOrder.batch_id == batch_id, OperationTask.batch_id == batch_id))
        .order_by(OperationPackage.version_number.desc())
    ).all()
    seen: set[str] = set()
    contexts: list[PackageContext] = []
    for package, order, task, channel, drama, schedule, slot in rows:
        if order.id in seen:
            continue
        seen.add(order.id)
        contexts.append(PackageContext(
            package_id=package.id,
            channel_id=channel.id,
            channel_name=channel.operational_name or channel.original_name,
            language=channel.default_language or channel.country_name_zh or "未设置语言",
            drama_id=drama.id,
            drama_title=drama.chinese_title,
            drama_code=drama.drama_code,
            drama_number=drama.drama_number,
            video_id=task.source_video_id,
            schedule_id=schedule.id if schedule else None,
            target_publish_date=str(order.target_publish_date),
            slot_type=slot.slot_type if slot else None,
            slot_number=slot.slot_number if slot else None,
        ))
    return contexts


def _schedule_folder(context: PackageContext) -> str:
    if context.slot_type:
        slot_label = "主档" if context.slot_type == "main" else "辅档"
        return f"{context.target_publish_date}_{slot_label}{context.slot_number or 1}"
    return f"{context.target_publish_date}_未排期"


def _context_path(base: Path, batch_number: str, context: PackageContext) -> Path:
    return (
        base
        / _safe_segment(batch_number, "未分批")
        / _safe_segment(context.language, "未设置语言")
        / _safe_segment(context.channel_name, context.channel_id)
        / _safe_segment(_schedule_folder(context), "未排期")
        / _safe_segment(context.drama_title, context.drama_code)
    )


def import_images(
    session: Session,
    batch_id: str,
    uploads: list[tuple[str, bytes]],
) -> ImageProcessingRunRead:
    batch = session.get(ProductionBatch, batch_id)
    if batch is None:
        raise ValueError("生产批次不存在")
    if not uploads:
        raise ValueError("请选择要导入的图片")
    setting = _workspace_setting(session)
    root, _, output = _ensure_workspace(setting)
    contexts = _package_contexts(session, batch.id)
    by_identifier: dict[str, list[PackageContext]] = {}
    for context in contexts:
        for identifier in context.identifiers:
            by_identifier.setdefault(identifier, []).append(context)
    identifiers = list(by_identifier)

    run = ImageProcessingRun(batch_id=batch.id, status="processing", total_files=len(uploads))
    session.add(run)
    session.flush()
    matched_count = 0
    unmatched_count = 0
    for original_name, data in uploads:
        match = classify_image_filename(original_name, identifiers)
        candidates = by_identifier.get(match.identifier or "", [])
        context = candidates[0] if len(candidates) == 1 else None
        extension = Path(original_name).suffix.lower() or ".png"
        if match.match_status == "matched" and context is not None and match.role:
            destination = _context_path(output / "图片导入", batch.batch_number, context) / "raw" / f"{match.role}{extension}"
            status = "matched"
            error = None
            matched_count += 1
        else:
            destination = output / "图片导入" / _safe_segment(batch.batch_number, batch.id) / "未匹配" / run.id / _safe_segment(original_name, "image")
            status = "ambiguous" if match.match_status == "ambiguous" or len(candidates) > 1 else "unmatched"
            error = "批次内匹配到多个运营包" if status == "ambiguous" else "文件名未匹配批次内的 Video ID 或剧目 ID"
            unmatched_count += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        session.add(ImageProcessingItem(
            run_id=run.id,
            original_filename=original_name,
            stored_path=_relative(root, destination),
            match_status=status,
            match_method=match.method,
            image_role=match.role,
            package_id=context.package_id if context else None,
            channel_id=context.channel_id if context else None,
            drama_id=context.drama_id if context else None,
            schedule_id=context.schedule_id if context else None,
            error_message=error,
        ))
    run.matched_files = matched_count
    run.unmatched_files = unmatched_count
    run.status = "classified" if unmatched_count == 0 else "partially_classified"
    run.completed_at = datetime.now(timezone.utc)
    report_path = output / "处理报告" / _safe_segment(batch.batch_number, batch.id) / f"{run.id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    run.manifest_path = _relative(root, report_path)
    session.commit()
    report_path.write_text(json.dumps(_run_manifest(session, run.id), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return get_processing_run(session, run.id)


def _run_manifest(session: Session, run_id: str) -> dict[str, object]:
    run = session.get(ImageProcessingRun, run_id)
    batch = session.get(ProductionBatch, run.batch_id) if run else None
    items = session.scalars(select(ImageProcessingItem).where(ImageProcessingItem.run_id == run_id).order_by(ImageProcessingItem.created_at)).all()
    return {
        "run_id": run_id,
        "batch_number": batch.batch_number if batch else None,
        "status": run.status if run else None,
        "items": [
            {
                "source": item.original_filename,
                "stored_path": item.stored_path,
                "match_status": item.match_status,
                "image_role": item.image_role,
                "output_path": item.output_path,
                "error": item.error_message,
            }
            for item in items
        ],
    }


def _compose_logo(source_path: Path, output_path: Path, profile: ChannelLogoProfile, root: Path) -> None:
    config = json.loads((root / profile.config_path).read_text(encoding="utf-8"))
    canvas = config["canvas"]
    with Image.open(source_path) as raw:
        base = raw.convert("RGBA").resize((canvas["width"], canvas["height"]), Image.Resampling.LANCZOS)
    for key, relative_logo in (("left_logo", profile.left_logo_path), ("right_logo", profile.right_logo_path)):
        region = config[key]
        with Image.open(root / relative_logo) as source_logo:
            logo = source_logo.convert("RGBA").resize(
                (max(1, round(region["width"] * base.width)), max(1, round(region["height"] * base.height))),
                Image.Resampling.LANCZOS,
            )
        base.alpha_composite(logo, (round(region["x"] * base.width), round(region["y"] * base.height)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(output_path, "PNG")


def generate_logos(session: Session, run_id: str) -> ImageProcessingRunRead:
    run = session.get(ImageProcessingRun, run_id)
    if run is None:
        raise ValueError("图片处理记录不存在")
    batch = session.get(ProductionBatch, run.batch_id)
    setting = _workspace_setting(session)
    root, _, output = _ensure_workspace(setting)
    contexts = {context.package_id: context for context in _package_contexts(session, run.batch_id)}
    profiles = {profile.channel_id: profile for profile in session.scalars(select(ChannelLogoProfile)).all()}
    items = session.scalars(
        select(ImageProcessingItem)
        .where(
            ImageProcessingItem.run_id == run.id,
            ImageProcessingItem.match_status == "matched",
            ImageProcessingItem.image_role.in_(LOGO_ROLES),
        )
        .order_by(ImageProcessingItem.created_at)
    ).all()
    generated = 0
    failed = 0
    for item in items:
        context = contexts.get(item.package_id or "")
        profile = profiles.get(item.channel_id or "")
        if context is None or profile is None or profile.status != "calibrated":
            item.error_message = "该频道尚未上传并校准 Logo 素材"
            failed += 1
            continue
        output_path = _context_path(output / "Logo成品", batch.batch_number, context) / f"{item.image_role}_logo.png"
        try:
            _compose_logo(root / item.stored_path, output_path, profile, root)
            item.output_path = _relative(root, output_path)
            item.error_message = None
            generated += 1
        except Exception as exc:
            item.error_message = f"Logo 生成失败：{exc}"
            failed += 1
    run.generated_files = generated
    run.status = "logo_ready" if items and failed == 0 else "partially_generated"
    run.completed_at = datetime.now(timezone.utc)
    session.commit()
    if run.manifest_path:
        (root / run.manifest_path).write_text(json.dumps(_run_manifest(session, run.id), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return get_processing_run(session, run.id)


def get_processing_run(session: Session, run_id: str) -> ImageProcessingRunRead:
    row = session.execute(
        select(ImageProcessingRun, ProductionBatch)
        .join(ProductionBatch, ProductionBatch.id == ImageProcessingRun.batch_id)
        .where(ImageProcessingRun.id == run_id)
    ).one_or_none()
    if row is None:
        raise ValueError("图片处理记录不存在")
    run, batch = row
    items = session.scalars(select(ImageProcessingItem).where(ImageProcessingItem.run_id == run.id).order_by(ImageProcessingItem.created_at)).all()
    return ImageProcessingRunRead(
        id=run.id,
        batch_id=run.batch_id,
        batch_number=batch.batch_number,
        status=run.status,
        total_files=run.total_files,
        matched_files=run.matched_files,
        unmatched_files=run.unmatched_files,
        generated_files=run.generated_files,
        manifest_path=run.manifest_path,
        error_message=run.error_message,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        items=[ImageProcessingItemRead.model_validate(item) for item in items],
    )


def list_processing_runs(session: Session, limit: int = 30) -> list[ImageProcessingRunRead]:
    run_ids = session.scalars(select(ImageProcessingRun.id).order_by(ImageProcessingRun.created_at.desc()).limit(limit)).all()
    return [get_processing_run(session, run_id) for run_id in run_ids]
