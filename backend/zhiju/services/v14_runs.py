from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models import (Channel, Drama, OperationPackage, PackageArtifact, PackageCommunityPost,
                          PackageCoverVariant, PackageDescription, PackageTitle, WorkOrder)
from zhiju.models.v14 import V14Run, V14Setting
from zhiju.services.identity import ConflictError
from zhiju.tenant_repository import require_tenant_entity
from zhiju.schemas.v14 import V14SettingsWrite


def get_settings(session: Session) -> V14Setting | None:
    return session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info["tenant_id"]))


def save_settings(session: Session, payload: dict) -> V14Setting:
    data = V14SettingsWrite.model_validate(payload).model_dump()
    setting = get_settings(session)
    if setting is None:
        setting = V14Setting(tenant_id=session.info["tenant_id"], payload=data)
        session.add(setting)
    else:
        setting.payload = deepcopy(data)
    session.commit()
    return setting


def get_run(session: Session, run_id: str) -> V14Run:
    return require_tenant_entity(session, V14Run, run_id, lock=True)


def create_run(session: Session, work_order_id: str) -> V14Run:
    work = require_tenant_entity(session, WorkOrder, work_order_id, lock=True)
    existing = session.scalar(select(V14Run).where(V14Run.work_order_id == work.id,
                                                  V14Run.tenant_id == session.info["tenant_id"]))
    if existing:
        return existing
    package = session.scalar(select(OperationPackage).where(OperationPackage.work_order_id == work.id,
        OperationPackage.tenant_id == session.info["tenant_id"]).order_by(OperationPackage.version_number.desc()))
    if package is None:
        raise ConflictError("工单缺少运营包，请先完成现有分发流程")
    for model in (PackageTitle, PackageDescription, PackageCoverVariant, PackageCommunityPost, PackageArtifact):
        if session.scalar(select(model.id).where(model.package_id == package.id).limit(1)):
            raise ConflictError("已有运营包结果，不能覆盖；请选择尚未生产的工单")
    if package.status != "building" or work.status != "queued":
        raise ConflictError("已有生产状态，不能覆盖；请选择尚未生产的工单")
    setting = get_settings(session)
    if setting is None:
        raise ConflictError("请先配置 V14 执行主机、模型和规则")
    config = setting.payload
    channel = require_tenant_entity(session, Channel, work.channel_id)
    drama = require_tenant_entity(session, Drama, work.drama_id)
    if channel.status != "active":
        raise ConflictError("频道未启用，不能运行")
    channel_input = config["channel_inputs"].get(channel.id)
    if not channel_input or not config["rules"]:
        raise ConflictError("缺少当前频道 V14 材料或固定规则")
    run = V14Run(tenant_id=session.info["tenant_id"], work_order_id=work.id, package_id=package.id,
        host_id=config["host_id"], account_profile=config["account_profile"], model=config["default_model"],
        rules_snapshot=deepcopy(config["rules"]), input_snapshot={
            "channel_id": channel.id, "channel_name": channel.original_name,
            "drama_id": drama.id, "drama_name": drama.chinese_title,
            "drama": {key: getattr(drama, key) for key in ("content_summary", "plot_archive", "plot_pattern", "core_personas")},
            "channel": deepcopy(channel_input), "community_count": work.community_count,
            "target_publish_date": str(work.target_publish_date),
        })
    session.add(run)
    session.commit()
    return run
