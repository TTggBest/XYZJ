from __future__ import annotations

import platform
import socket
import base64
import shutil
import subprocess
import tarfile
import tempfile
import io
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.config import APP_ROOT, get_settings
from zhiju.database import can_switch_database_environment, database_router
from zhiju.models import (
    AppIconSetting,
    ChannelDramaType,
    RuntimePackageBuild,
    Skill,
    SkillVersion,
)
from zhiju.schemas.settings import ChannelDramaTypeCreate, ChannelDramaTypeUpdate
from zhiju.services.identity import ConflictError


APP_VERSION = "3.0.0-dev.1"
PACKAGE_VERSION = "3.0.0"
PACKAGE_TARGET_ENVIRONMENT = "production"
ICON_RUNTIME_ROOT = APP_ROOT / ".runtime" / "settings"
DEFAULT_ICON_PATH = APP_ROOT / "assets" / "app-icon-source-default.png"
WEB_ICON_PATH = APP_ROOT / "assets" / "app-icon-1024.png"
DESKTOP_APP_PATH = Path.home() / "Desktop" / "筱宇智矩.app"
DESKTOP_ICON_PATH = DESKTOP_APP_PATH / "Contents" / "Resources" / "applet.icns"
DESKTOP_BUNDLE_ID = "local.xiaoyu.zhiju"
APP_ICON_SETTING_ID = "current-app-icon"
EXCLUDED_NAMES = {
    ".env",
    ".runtime",
    ".server.pid",
    ".server.port",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "data",
    "server.log",
    "tests",
}
PACKAGE_ROOT_FILES = {
    "alembic.ini",
    "index.html",
    "pyproject.toml",
    "README.md",
    "requirements-runtime.txt",
    "run_v3.py",
    "uv.lock",
}
PACKAGE_DIRECTORIES = {"assets", "backend", "scripts"}
PACKAGE_EXCLUDED_FILES = {"scripts/mysql_dev.sh"}

CHANNEL_INITIALIZATION_MODULES = (
    ("description", "频道说明", "channel-description", "频道定位与说明正文"),
    ("keywords_tags", "关键词与标签", "channel-keywords-tags", "频道关键词和标签"),
    ("avatar_prompt", "头像出图词", "channel-avatar-prompt", "频道头像生成提示词"),
    ("banner_prompt", "横幅出图词", "channel-banner-prompt", "频道横幅生成提示词"),
    ("pinned_comment", "置顶评论", "channel-pinned-comment", "频道置顶评论正文"),
    ("title_template", "标题模板", "channel-title-template", "频道标题结构模板"),
    ("popup_scheme", "弹框方案", "channel-popup-scheme", "频道弹框运营方案"),
    ("playlists", "播放列表", "channel-playlists", "三条播放列表名称与说明"),
    ("initial_audience", "初始用户画像", "channel-initial-audience", "频道初始受众假设"),
    ("initial_analysis", "初始分析报告", "channel-initial-analysis", "频道初始化分析报告"),
    ("operating_reference", "运营参考", "channel-operating-reference", "频道排期与运营包参考"),
)


def list_channel_initialization_rules(session: Session) -> list[dict[str, object]]:
    codes = [item[2] for item in CHANNEL_INITIALIZATION_MODULES]
    skills = {
        row.code: row
        for row in session.scalars(select(Skill).where(Skill.code.in_(codes)))
    }
    current_versions = (
        {
            row.skill_id: row
            for row in session.scalars(
                select(SkillVersion).where(
                    SkillVersion.skill_id.in_([row.id for row in skills.values()]),
                    SkillVersion.is_current.is_(True),
                )
            )
        }
        if skills
        else {}
    )
    result = []
    for module_key, module_name, skill_code, output_description in CHANNEL_INITIALIZATION_MODULES:
        skill = skills.get(skill_code)
        version = current_versions.get(skill.id) if skill else None
        readiness = (
            "ready"
            if version
            else "missing_published_version"
            if skill
            else "missing_skill"
        )
        result.append(
            {
                "module_key": module_key,
                "module_name": module_name,
                "output_description": output_description,
                "skill_code": skill_code,
                "skill_id": skill.id if skill else None,
                "current_version_id": version.id if version else None,
                "current_version_number": version.version_number if version else None,
                "current_version_status": version.status if version else None,
                "readiness": readiness,
            }
        )
    return result


def list_channel_drama_types(
    session: Session, *, include_disabled: bool = False
) -> list[ChannelDramaType]:
    statement = select(ChannelDramaType)
    if not include_disabled:
        statement = statement.where(ChannelDramaType.status == "active")
    return list(
        session.scalars(
            statement.order_by(ChannelDramaType.sort_order, ChannelDramaType.name)
        )
    )


def create_channel_drama_type(
    session: Session, payload: ChannelDramaTypeCreate
) -> ChannelDramaType:
    row = ChannelDramaType(**payload.model_dump())
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("短剧类型编码或名称已存在") from exc
    session.refresh(row)
    return row


def update_channel_drama_type(
    session: Session, type_id: str, payload: ChannelDramaTypeUpdate
) -> ChannelDramaType:
    row = session.get(ChannelDramaType, type_id)
    if row is None:
        raise ValueError("短剧类型不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("短剧类型名称已存在") from exc
    session.refresh(row)
    return row


def runtime_overview(session: Session) -> dict[str, object]:
    settings = get_settings()
    database_url = make_url(database_router.active_database_url)
    database_ok = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        database_ok = False
    return {
        "system": "筱宇智矩",
        "version": APP_VERSION,
        "environment": database_router.active_environment,
        "base_environment": settings.env,
        "can_switch_environment": can_switch_database_environment(),
        "host": settings.host,
        "port": settings.port,
        "database_host": database_url.host or "",
        "database_port": database_url.port,
        "database_name": database_url.database or "",
        "database_ok": database_ok,
        "project_root": str(APP_ROOT),
        "artifact_root": str(settings.artifact_root),
        "hostname": socket.gethostname(),
        "operating_system": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "device_role": settings.device_role,
        "realtime_hub_url": settings.realtime_hub_url or "本机 SSE",
    }


def list_runtime_packages(session: Session) -> list[RuntimePackageBuild]:
    return list(session.scalars(select(RuntimePackageBuild).order_by(RuntimePackageBuild.build_number.desc())))


def _included_files() -> list[Path]:
    files: list[Path] = []
    for path in APP_ROOT.rglob("*"):
        relative = path.relative_to(APP_ROOT)
        relative_text = relative.as_posix()
        if relative_text in PACKAGE_EXCLUDED_FILES:
            continue
        if relative.parts[0] not in PACKAGE_DIRECTORIES and relative_text not in PACKAGE_ROOT_FILES:
            continue
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.is_file() and path.suffix not in {".pyc", ".log"}:
            files.append(path)
    return sorted(files)


def _write_runtime_archive(artifact, version: str) -> tuple[int, int]:
    files = _included_files()
    root = Path(f"zhiju-runtime-{version}")
    open_args = {"fileobj": artifact} if hasattr(artifact, "write") else {"name": artifact}
    with tarfile.open(mode="w:gz", **open_args) as archive:
        for path in files:
            archive.add(path, arcname=root / path.relative_to(APP_ROOT), recursive=False)
        version_bytes = f"{version}\n".encode("utf-8")
        version_info = tarfile.TarInfo(str(root / "VERSION"))
        version_info.size = len(version_bytes)
        version_info.mode = 0o644
        archive.addfile(version_info, io.BytesIO(version_bytes))
    size_bytes = artifact.tell() if hasattr(artifact, "tell") else artifact.stat().st_size
    return len(files) + 1, size_bytes


def build_runtime_package(session: Session) -> RuntimePackageBuild:
    settings = get_settings()
    build_number = int(session.scalar(select(func.coalesce(func.max(RuntimePackageBuild.build_number), 0))) or 0) + 1
    version = f"{PACKAGE_VERSION}-build.{build_number}"
    now = datetime.now(timezone.utc)
    build = RuntimePackageBuild(
        build_number=build_number,
        version=version,
        target_environment=PACKAGE_TARGET_ENVIRONMENT,
        status="building",
        started_at=now,
    )
    session.add(build)
    session.commit()
    session.refresh(build)

    try:
        with tempfile.TemporaryDirectory(prefix="zhiju-build-") as temp_dir:
            artifact = Path(temp_dir) / f"zhiju-{version}.tar.gz"
            file_count, size_bytes = _write_runtime_archive(artifact, version)
        build.status = "succeeded"
        build.artifact_path = None
        build.file_count = file_count
        build.size_bytes = size_bytes
        build.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        build.status = "failed"
        build.error_message = str(exc)
        build.completed_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(build)
    return build


def get_current_runtime_package(session: Session, build_id: str) -> RuntimePackageBuild:
    current = session.scalar(select(RuntimePackageBuild).order_by(RuntimePackageBuild.build_number.desc()).limit(1))
    if current is None or current.id != build_id:
        raise ValueError("只能下载当前最新构建版本")
    if current.status != "succeeded":
        raise ValueError("当前版本尚未构建成功")
    return current


def stream_runtime_package(build: RuntimePackageBuild):
    with tempfile.TemporaryDirectory(prefix="zhiju-download-") as temp_dir:
        artifact = Path(temp_dir) / f"zhiju-{build.version}.tar.gz"
        _write_runtime_archive(artifact, build.version)
        with artifact.open("rb") as package_file:
            while chunk := package_file.read(1024 * 1024):
                yield chunk


def _icon_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    values: dict[str, int] = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, value = line.strip().split(":", 1)
            if value.strip().isdigit():
                values[key] = int(value.strip())
    return values.get("pixelWidth", 0), values.get("pixelHeight", 0)


def _render_icon(source: Path) -> None:
    width, height = _icon_dimensions(source)
    if width != height or width < 512:
        raise ValueError("应用图标必须是至少 512×512 的正方形图片")
    with tempfile.TemporaryDirectory(prefix="zhiju-icon-") as temp_dir:
        temp = Path(temp_dir)
        png = temp / "app-icon-1024.png"
        subprocess.run(
            ["/usr/bin/swift", str(APP_ROOT / "tools" / "render_app_icon.swift"), str(source), str(png)],
            check=True,
            capture_output=True,
        )
        iconset = temp / "applet.iconset"
        iconset.mkdir()
        sizes = [(16, "icon_16x16.png"), (32, "icon_16x16@2x.png"), (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"), (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"), (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"), (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")]
        for size, name in sizes:
            subprocess.run(["sips", "-z", str(size), str(size), str(png), "--out", str(iconset / name)], check=True, capture_output=True)
        icns = temp / "applet.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True, capture_output=True)
        shutil.copy2(png, WEB_ICON_PATH)
        if DESKTOP_APP_PATH.exists():
            subprocess.run(["/usr/bin/swift", str(APP_ROOT / "tools" / "apply_app_icon.swift"), "--clear", str(DESKTOP_APP_PATH)], check=True, capture_output=True)
            shutil.copy2(icns, DESKTOP_ICON_PATH)
            plist = str(DESKTOP_APP_PATH / "Contents" / "Info.plist")
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Delete :CFBundleIconName", plist], check=False, capture_output=True)
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Set :CFBundleName 筱宇智矩", plist], check=True, capture_output=True)
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Set :CFBundleDisplayName 筱宇智矩", plist], check=False, capture_output=True)
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", f"Add :CFBundleDisplayName string 筱宇智矩", plist], check=False, capture_output=True)
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", f"Set :CFBundleIdentifier {DESKTOP_BUNDLE_ID}", plist], check=False, capture_output=True)
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", f"Add :CFBundleIdentifier string {DESKTOP_BUNDLE_ID}", plist], check=False, capture_output=True)
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Set :CFBundleIconFile applet.icns", plist], check=True, capture_output=True)
            subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(DESKTOP_APP_PATH)], check=True, capture_output=True)
            subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister", "-f", str(DESKTOP_APP_PATH)], check=True, capture_output=True)
            DESKTOP_APP_PATH.touch()
            subprocess.run(["/usr/bin/killall", "Finder"], check=False, capture_output=True)


def _icon_response(setting: AppIconSetting) -> dict[str, object]:
    return {
        "id": setting.id,
        "source_type": setting.source_type,
        "original_filename": setting.original_filename,
        "preview_url": f"/assets/app-icon-1024.png?v={int(setting.applied_at.timestamp())}",
        "desktop_app_path": str(DESKTOP_APP_PATH),
        "applied_at": setting.applied_at,
        "updated_at": setting.updated_at,
    }


def get_app_icon_setting(session: Session) -> dict[str, object]:
    setting = session.get(AppIconSetting, APP_ICON_SETTING_ID)
    if setting is None:
        raise RuntimeError("应用图标设置尚未初始化")
    return _icon_response(setting)


def upload_app_icon(session: Session, filename: str, data_url: str) -> dict[str, object]:
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError as exc:
        raise ValueError("上传的图标数据格式无效") from exc
    if header not in {"data:image/png;base64", "data:image/jpeg;base64"}:
        raise ValueError("只支持 PNG 或 JPEG 图标")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("图标文件不能超过 10 MB")
    ICON_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    source = ICON_RUNTIME_ROOT / "app-icon-custom"
    source = source.with_suffix(".png" if header.startswith("data:image/png") else ".jpg")
    source.write_bytes(raw)
    _render_icon(source)
    now = datetime.now(timezone.utc)
    setting = session.get(AppIconSetting, APP_ICON_SETTING_ID)
    if setting is None:
        setting = AppIconSetting(id=APP_ICON_SETTING_ID, source_type="custom", source_path=str(source), applied_at=now)
        session.add(setting)
    setting.source_type = "custom"
    setting.source_path = str(source)
    setting.original_filename = filename
    setting.applied_at = now
    session.commit()
    session.refresh(setting)
    return _icon_response(setting)


def restore_default_app_icon(session: Session) -> dict[str, object]:
    if not DEFAULT_ICON_PATH.exists():
        raise RuntimeError("默认应用图标不存在")
    _render_icon(DEFAULT_ICON_PATH)
    now = datetime.now(timezone.utc)
    setting = session.get(AppIconSetting, APP_ICON_SETTING_ID)
    if setting is None:
        setting = AppIconSetting(id=APP_ICON_SETTING_ID, source_type="default", source_path=str(DEFAULT_ICON_PATH), applied_at=now)
        session.add(setting)
    setting.source_type = "default"
    setting.source_path = str(DEFAULT_ICON_PATH)
    setting.original_filename = DEFAULT_ICON_PATH.name
    setting.applied_at = now
    session.commit()
    session.refresh(setting)
    return _icon_response(setting)
