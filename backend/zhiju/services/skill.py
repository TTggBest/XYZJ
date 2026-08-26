from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import Skill, SkillVersion
from zhiju.schemas.skill import (
    SkillCreate,
    SkillUpdate,
    SkillVersionCreate,
    SkillVersionUpdate,
)
from zhiju.services.identity import ConflictError, _audit


class SkillNotFoundError(Exception):
    pass


def _skill(session: Session, skill_id: str, *, lock: bool = False) -> Skill:
    statement = select(Skill).where(Skill.id == skill_id)
    if lock:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise SkillNotFoundError("Skill不存在")
    return row


def _version(
    session: Session, skill_id: str, version_id: str, *, lock: bool = False
) -> SkillVersion:
    statement = select(SkillVersion).where(
        SkillVersion.id == version_id, SkillVersion.skill_id == skill_id
    )
    if lock:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise SkillNotFoundError("Skill版本不存在")
    return row


def _normalized_content(body_zh_cn: str, body_original: str) -> tuple[str, str, str]:
    chinese = body_zh_cn.strip()
    original = body_original.strip()
    digest = sha256(f"{chinese}\0{original}".encode("utf-8")).hexdigest()
    return chinese, original, digest


def create_skill(session: Session, payload: SkillCreate) -> Skill:
    values = payload.model_dump()
    values.update(
        code=payload.code.strip().lower(),
        name=payload.name.strip(),
        purpose=payload.purpose.strip(),
        category=payload.category.strip().lower(),
    )
    row = Skill(**values)
    session.add(row)
    try:
        session.flush()
        _audit(session, "skill.created", "skill", row.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Skill代码已经存在") from exc
    session.refresh(row)
    return row


def list_skills(
    session: Session,
    *,
    status: str | None = None,
    category: str | None = None,
    query: str | None = None,
) -> list[Skill]:
    statement = select(Skill)
    if status:
        statement = statement.where(Skill.status == status)
    if category:
        statement = statement.where(Skill.category == category.strip().lower())
    if query:
        term = f"%{query.strip()}%"
        statement = statement.where(
            Skill.code.like(term) | Skill.name.like(term) | Skill.purpose.like(term)
        )
    return list(session.scalars(statement.order_by(Skill.category, Skill.code)))


def get_skill_detail(session: Session, skill_id: str) -> dict[str, object]:
    row = _skill(session, skill_id)
    current = session.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill_id, SkillVersion.is_current.is_(True)
        )
    )
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "purpose": row.purpose,
        "category": row.category,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "current_version": current,
    }


def update_skill(session: Session, skill_id: str, payload: SkillUpdate) -> Skill:
    row = _skill(session, skill_id, lock=True)
    values = payload.model_dump(exclude_unset=True)
    for field in ("name", "purpose"):
        if field in values:
            values[field] = values[field].strip()
    if "category" in values:
        values["category"] = values["category"].strip().lower()
    for field, value in values.items():
        setattr(row, field, value)
    _audit(session, "skill.updated", "skill", row.id)
    session.commit()
    session.refresh(row)
    return row


def create_skill_version(
    session: Session, skill_id: str, payload: SkillVersionCreate
) -> SkillVersion:
    skill = _skill(session, skill_id, lock=True)
    if skill.status != "active":
        raise ConflictError("只有启用中的Skill可以创建新版本")
    next_number = (
        session.scalar(
            select(func.max(SkillVersion.version_number)).where(
                SkillVersion.skill_id == skill_id
            )
        )
        or 0
    ) + 1
    chinese, original, digest = _normalized_content(
        payload.body_zh_cn, payload.body_original
    )
    row = SkillVersion(
        skill_id=skill_id,
        version_number=next_number,
        body_zh_cn=chinese,
        body_original=original,
        content_sha256=digest,
        status="draft",
        is_current=None,
        change_summary=payload.change_summary,
        created_by=payload.created_by,
    )
    session.add(row)
    try:
        session.flush()
        _audit(session, "skill_version.created", "skill_version", row.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该Skill版本内容已经存在或版本号冲突") from exc
    session.refresh(row)
    return row


def list_skill_versions(session: Session, skill_id: str) -> list[SkillVersion]:
    _skill(session, skill_id)
    return list(
        session.scalars(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id)
            .order_by(SkillVersion.version_number.desc())
        )
    )


def get_skill_version(
    session: Session, skill_id: str, version_id: str
) -> SkillVersion:
    _skill(session, skill_id)
    return _version(session, skill_id, version_id)


def update_skill_version(
    session: Session,
    skill_id: str,
    version_id: str,
    payload: SkillVersionUpdate,
) -> SkillVersion:
    _skill(session, skill_id, lock=True)
    row = _version(session, skill_id, version_id, lock=True)
    if row.status != "draft":
        raise ConflictError("已发布或归档的Skill版本不可覆盖，只能创建新版本")
    values = payload.model_dump(exclude_unset=True)
    chinese = values.pop("body_zh_cn", row.body_zh_cn)
    original = values.pop("body_original", row.body_original)
    row.body_zh_cn, row.body_original, row.content_sha256 = _normalized_content(
        chinese, original
    )
    for field, value in values.items():
        setattr(row, field, value)
    try:
        session.flush()
        _audit(session, "skill_version.updated", "skill_version", row.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该Skill版本内容已经存在") from exc
    session.refresh(row)
    return row


def publish_skill_version(
    session: Session, skill_id: str, version_id: str
) -> SkillVersion:
    skill = _skill(session, skill_id, lock=True)
    if skill.status != "active":
        raise ConflictError("只有启用中的Skill可以发布版本")
    row = _version(session, skill_id, version_id, lock=True)
    if row.status == "published" and row.is_current:
        return row
    if row.status != "draft":
        raise ConflictError("只有草稿版本可以发布")
    current = session.scalar(
        select(SkillVersion)
        .where(
            SkillVersion.skill_id == skill_id, SkillVersion.is_current.is_(True)
        )
        .with_for_update()
    )
    if current is not None:
        current.status = "superseded"
        current.is_current = None
    row.status = "published"
    row.is_current = True
    row.published_at = datetime.now(timezone.utc)
    session.flush()
    _audit(
        session,
        "skill_version.published",
        "skill_version",
        row.id,
        change_summary=f"skill_id={skill_id};version={row.version_number}",
    )
    session.commit()
    session.refresh(row)
    return row
