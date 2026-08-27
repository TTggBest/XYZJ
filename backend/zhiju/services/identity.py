from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import (
    AccountChannelAuthorization,
    AuditEvent,
    AuthorizationEvent,
    Channel,
    ChannelAnalysisReport,
    ChannelDnaVersion,
    ChannelProfile,
    ChannelScheduleEntry,
    Device,
    GoogleAccount,
    MediaAsset,
    OAuthGrant,
    OAuthGrantScope,
    OperationPackage,
    OperationTask,
    ProductionNodeRun,
    ScheduleChangeHistory,
    SyncWatermark,
    SystemEvent,
    TaskEvent,
    WorkOrder,
)
from zhiju.schemas.identity import (
    AccountCreate,
    ChannelAuthorizationVerify,
    ChannelCreate,
    ChannelStatusChange,
    DeviceRegister,
    OAuthGrantCreate,
)


class ConflictError(Exception):
    pass


class IdentityNotFoundError(Exception):
    pass


ALLOWED_CHANNEL_TRANSITIONS = {
    "new": {"authorized", "paused", "archived"},
    "authorized": {"analyzed", "paused", "archived"},
    "analyzed": {"branded", "paused", "archived"},
    "branded": {"configured", "paused", "archived"},
    "configured": {"scheduled", "active", "paused", "archived"},
    "scheduled": {"active", "paused", "archived"},
    "active": {"paused", "archived"},
    "paused": {"active", "archived"},
    "archived": set(),
    "deleted": set(),
}


def _audit(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    change_summary: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_type="system",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            change_summary=change_summary,
            occurred_at=datetime.now(timezone.utc),
        )
    )


def create_account(session: Session, payload: AccountCreate) -> GoogleAccount:
    account = GoogleAccount(nickname=payload.nickname.strip(), google_email=str(payload.google_email).lower())
    session.add(account)
    try:
        session.flush()
        _audit(session, "account.created", "google_account", account.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Google账号已存在") from exc
    session.refresh(account)
    return account


def list_accounts(session: Session) -> list[GoogleAccount]:
    return list(session.scalars(select(GoogleAccount).order_by(GoogleAccount.created_at.desc())))


def list_devices(session: Session) -> list[Device]:
    return list(session.scalars(select(Device).order_by(Device.last_seen_at.desc(), Device.created_at.desc())))


def create_channel(session: Session, payload: ChannelCreate) -> Channel:
    channel = Channel(**payload.model_dump())
    session.add(channel)
    try:
        session.flush()
        _audit(session, "channel.created", "channel", channel.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("YouTube频道已存在") from exc
    session.refresh(channel)
    return channel


def list_channels(session: Session, *, include_archived: bool = False) -> list[Channel]:
    statement = select(Channel)
    if not include_archived:
        statement = statement.where(Channel.deleted_at.is_(None), Channel.status != "archived")
    statement = statement.order_by(Channel.created_at.desc())
    return list(session.scalars(statement))


def list_channel_overview(
    session: Session,
    *,
    include_archived: bool = False,
    status: str | None = None,
    language: str | None = None,
) -> list[dict[str, object]]:
    statement = select(Channel)
    if not include_archived:
        statement = statement.where(
            Channel.deleted_at.is_(None), Channel.status != "archived"
        )
    if status:
        statement = statement.where(Channel.status == status)
    if language:
        statement = statement.where(Channel.default_language == language)
    channels = list(
        session.scalars(
            statement.order_by(Channel.operational_name, Channel.original_name, Channel.id)
        )
    )
    channel_ids = [channel.id for channel in channels]
    if not channel_ids:
        return []

    authorization_rows = list(
        session.execute(
            select(AccountChannelAuthorization, GoogleAccount)
            .join(GoogleAccount, GoogleAccount.id == AccountChannelAuthorization.account_id)
            .where(
                AccountChannelAuthorization.channel_id.in_(channel_ids),
                AccountChannelAuthorization.status == "active",
            )
            .order_by(
                AccountChannelAuthorization.channel_id,
                GoogleAccount.nickname,
                GoogleAccount.google_email,
            )
        )
    )
    accounts_by_channel: dict[str, list[dict[str, object]]] = {}
    for authorization, account in authorization_rows:
        accounts_by_channel.setdefault(authorization.channel_id, []).append(
            {
                "authorization_id": authorization.id,
                "account_id": account.id,
                "nickname": account.nickname,
                "google_email": account.google_email,
                "account_status": account.status,
                "authorization_status": account.authorization_status,
                "verified_at": authorization.verified_at,
            }
        )

    profiles = {
        profile.channel_id: profile
        for profile in session.scalars(
            select(ChannelProfile).where(ChannelProfile.channel_id.in_(channel_ids))
        )
    }
    avatar_ids = [
        profile.avatar_asset_id for profile in profiles.values() if profile.avatar_asset_id
    ]
    avatars = (
        {
            asset.id: asset
            for asset in session.scalars(
                select(MediaAsset).where(MediaAsset.id.in_(avatar_ids))
            )
        }
        if avatar_ids
        else {}
    )

    dna_rows = list(
        session.scalars(
            select(ChannelDnaVersion)
            .where(ChannelDnaVersion.channel_id.in_(channel_ids))
            .order_by(
                ChannelDnaVersion.channel_id,
                ChannelDnaVersion.version_number.desc(),
            )
        )
    )
    dna_by_channel: dict[str, list[ChannelDnaVersion]] = {}
    for dna in dna_rows:
        dna_by_channel.setdefault(dna.channel_id, []).append(dna)

    report_rows = list(
        session.scalars(
            select(ChannelAnalysisReport)
            .where(ChannelAnalysisReport.channel_id.in_(channel_ids))
            .order_by(
                ChannelAnalysisReport.channel_id,
                ChannelAnalysisReport.version_number.desc(),
            )
        )
    )
    reports_by_channel: dict[str, list[ChannelAnalysisReport]] = {}
    for report in report_rows:
        reports_by_channel.setdefault(report.channel_id, []).append(report)

    watermark_rows = list(
        session.scalars(
            select(SyncWatermark).where(SyncWatermark.channel_id.in_(channel_ids))
        )
    )
    watermarks_by_channel: dict[str, list[SyncWatermark]] = {}
    for watermark in watermark_rows:
        watermarks_by_channel.setdefault(watermark.channel_id, []).append(watermark)

    result = []
    for channel in channels:
        accounts = accounts_by_channel.get(channel.id, [])
        profile = profiles.get(channel.id)
        avatar = (
            avatars.get(profile.avatar_asset_id)
            if profile and profile.avatar_asset_id
            else None
        )
        dna_versions = dna_by_channel.get(channel.id, [])
        latest_dna = next(
            (dna for dna in dna_versions if dna.status == "active"),
            dna_versions[0] if dna_versions else None,
        )
        reports = reports_by_channel.get(channel.id, [])
        latest_report = reports[0] if reports else None
        watermarks = watermarks_by_channel.get(channel.id, [])
        completed_sync_times = [
            watermark.last_completed_at
            for watermark in watermarks
            if watermark.last_completed_at is not None
        ]
        result.append(
            {
                "channel_id": channel.id,
                "youtube_channel_id": channel.youtube_channel_id,
                "original_name": channel.original_name,
                "operational_name": channel.operational_name,
                "display_name": channel.operational_name or channel.original_name,
                "youtube_avatar_url": channel.youtube_avatar_url,
                "country_code": channel.country_code,
                "country_name_zh": channel.country_name_zh,
                "default_language": channel.default_language,
                "default_genre": channel.default_genre,
                "timezone": channel.timezone,
                "daily_publish_count": channel.daily_publish_count,
                "status": channel.status,
                "deleted_at": channel.deleted_at,
                "authorized_account_count": len(accounts),
                "authorized_accounts": accounts,
                "profile_id": profile.id if profile else None,
                "profile_status": profile.status if profile else None,
                "positioning": profile.positioning if profile else None,
                "avatar_asset_id": avatar.id if avatar else None,
                "avatar_storage_provider": avatar.storage_provider if avatar else None,
                "avatar_storage_key": avatar.storage_key if avatar else None,
                "avatar_status": avatar.status if avatar else None,
                "dna_version_count": len(dna_versions),
                "latest_dna_version_id": latest_dna.id if latest_dna else None,
                "latest_dna_version_number": latest_dna.version_number if latest_dna else None,
                "latest_dna_status": latest_dna.status if latest_dna else None,
                "latest_dna_primary_genre": latest_dna.primary_genre if latest_dna else None,
                "latest_dna_secondary_genre": latest_dna.secondary_genre if latest_dna else None,
                "latest_dna_updated_at": latest_dna.updated_at if latest_dna else None,
                "analysis_report_count": len(reports),
                "latest_analysis_report_id": latest_report.id if latest_report else None,
                "latest_analysis_version_number": latest_report.version_number if latest_report else None,
                "latest_analysis_status": latest_report.status if latest_report else None,
                "latest_analysis_at": latest_report.updated_at if latest_report else None,
                "last_sync_at": max(completed_sync_times) if completed_sync_times else None,
                "running_sync_count": sum(
                    watermark.status == "running" for watermark in watermarks
                ),
                "created_at": channel.created_at,
                "updated_at": channel.updated_at,
            }
        )
    return result


def _status_event(
    session: Session,
    entity_type: str,
    entity_id: str,
    old_status: str | None,
    new_status: str,
    reason: str,
) -> None:
    session.add(
        SystemEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            actor_type="system",
            occurred_at=datetime.now(timezone.utc),
        )
    )


def _set_channel_status(
    session: Session,
    channel: Channel,
    new_status: str,
    reason: str,
) -> None:
    old_status = channel.status
    channel.status = new_status
    _status_event(session, "channel", channel.id, old_status, new_status, reason)


def _stop_channel_operations(
    session: Session,
    channel: Channel,
    reason: str,
) -> None:
    now = datetime.now(timezone.utc)
    schedules = list(
        session.scalars(
            select(ChannelScheduleEntry)
            .where(
                ChannelScheduleEntry.channel_id == channel.id,
                ChannelScheduleEntry.status.in_(("planned", "reserved", "confirmed")),
            )
            .with_for_update()
        )
    )
    for schedule in schedules:
        old_status = schedule.status
        schedule.status = "cancelled"
        session.add(
            ScheduleChangeHistory(
                schedule_id=schedule.id,
                old_drama_id=schedule.drama_id,
                new_drama_id=schedule.drama_id,
                old_planned_utc_time=schedule.planned_utc_time,
                new_planned_utc_time=schedule.planned_utc_time,
                old_status=old_status,
                new_status="cancelled",
                reason=reason,
                actor_type="system",
                changed_at=now,
            )
        )
        _status_event(session, "channel_schedule_entry", schedule.id, old_status, "cancelled", reason)

    tasks = list(
        session.scalars(
            select(OperationTask)
            .where(
                OperationTask.channel_id == channel.id,
                OperationTask.status.in_(("pending_dispatch", "dispatched", "processing")),
            )
            .with_for_update()
        )
    )
    for task in tasks:
        old_status = task.status
        task.status = "cancelled"
        task.failure_reason = reason
        session.add(
            TaskEvent(
                task_id=task.id,
                old_status=old_status,
                new_status="cancelled",
                reason=reason,
                actor_type="system",
                occurred_at=now,
            )
        )
        _status_event(session, "operation_task", task.id, old_status, "cancelled", reason)

    work_orders = list(
        session.scalars(
            select(WorkOrder)
            .where(
                WorkOrder.channel_id == channel.id,
                WorkOrder.status.in_(("queued", "running")),
            )
            .with_for_update()
        )
    )
    for work_order in work_orders:
        old_status = work_order.status
        work_order.status = "cancelled"
        work_order.failure_reason = reason
        _status_event(session, "work_order", work_order.id, old_status, "cancelled", reason)

    nodes = list(
        session.scalars(
            select(ProductionNodeRun)
            .join(WorkOrder, WorkOrder.id == ProductionNodeRun.work_order_id)
            .where(
                WorkOrder.channel_id == channel.id,
                ProductionNodeRun.status.in_(("pending", "queued", "running")),
            )
            .with_for_update()
        )
    )
    for node in nodes:
        old_status = node.status
        node.status = "cancelled"
        node.worker_key = None
        node.completed_at = now
        _status_event(session, "production_node_run", node.id, old_status, "cancelled", reason)

    packages = list(
        session.scalars(
            select(OperationPackage)
            .where(
                OperationPackage.channel_id == channel.id,
                OperationPackage.status.not_in(("approved", "delivered", "archived")),
            )
            .with_for_update()
        )
    )
    for package in packages:
        old_status = package.status
        package.status = "archived"
        _status_event(session, "operation_package", package.id, old_status, "archived", reason)

    watermarks = list(
        session.scalars(
            select(SyncWatermark)
            .where(SyncWatermark.channel_id == channel.id, SyncWatermark.status == "running")
            .with_for_update()
        )
    )
    for watermark in watermarks:
        watermark.status = "failed"
        watermark.last_failed_at = now
        watermark.error_code = "CHANNEL_ARCHIVED"
        watermark.error_message = reason
        watermark.lease_owner = None
        watermark.lease_expires_at = None
        _status_event(session, "sync_watermark", watermark.id, "running", "failed", reason)


def change_channel_status(
    session: Session,
    channel_id: str,
    payload: ChannelStatusChange,
) -> Channel:
    channel = _require_channel(session, channel_id, lock=True)
    if payload.status not in ALLOWED_CHANNEL_TRANSITIONS.get(channel.status, set()):
        raise ConflictError(f"频道不能从 {channel.status} 变更为 {payload.status}")
    if payload.status == "archived":
        _stop_channel_operations(session, channel, payload.reason)
    _set_channel_status(session, channel, payload.status, payload.reason)
    _audit(session, "channel.status_changed", "channel", channel.id, payload.reason)
    session.commit()
    session.refresh(channel)
    return channel


def archive_channel(session: Session, channel_id: str, reason: str) -> Channel:
    channel = _require_channel(session, channel_id, lock=True)
    if channel.status == "archived":
        if channel.deleted_at is None:
            channel.deleted_at = datetime.now(timezone.utc)
            _audit(session, "channel.soft_deleted", "channel", channel.id, reason)
            session.commit()
            session.refresh(channel)
        return channel
    _stop_channel_operations(session, channel, reason)
    if channel.status == "active":
        _set_channel_status(session, channel, "paused", reason)
    _set_channel_status(session, channel, "archived", reason)
    channel.deleted_at = datetime.now(timezone.utc)
    _audit(session, "channel.soft_deleted", "channel", channel.id, reason)
    session.commit()
    session.refresh(channel)
    return channel


def register_device(session: Session, payload: DeviceRegister) -> Device:
    matches = list(
        session.scalars(
            select(Device).where(
                or_(Device.device_key == payload.device_key, Device.hostname == payload.hostname)
            )
        )
    )
    if len(matches) > 1:
        raise ConflictError("设备标识和主机名分别属于不同设备")
    device = matches[0] if matches else None
    now = datetime.now(timezone.utc)
    if device is None:
        device = Device(**payload.model_dump(), last_seen_at=now)
        session.add(device)
        session.flush()
        action = "device.created"
    else:
        for field, value in payload.model_dump().items():
            setattr(device, field, value)
        device.last_seen_at = now
        action = "device.updated"
    _audit(session, action, "device", device.id)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("设备标识或主机名已被占用") from exc
    session.refresh(device)
    return device


def _require_account(session: Session, account_id: str) -> GoogleAccount:
    account = session.get(GoogleAccount, account_id)
    if account is None:
        raise IdentityNotFoundError("Google账号不存在")
    return account


def _require_channel(session: Session, channel_id: str, *, lock: bool = False) -> Channel:
    statement = select(Channel).where(Channel.id == channel_id, Channel.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    channel = session.scalar(statement)
    if channel is None:
        raise IdentityNotFoundError("频道不存在")
    return channel


def _require_device(session: Session, device_id: str | None) -> Device | None:
    if device_id is None:
        return None
    device = session.get(Device, device_id)
    if device is None:
        raise IdentityNotFoundError("授权设备不存在")
    return device


def _authorization_event(
    session: Session,
    *,
    event_type: str,
    result: str,
    account_id: str | None = None,
    channel_id: str | None = None,
    device_id: str | None = None,
    oauth_grant_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> AuthorizationEvent:
    event = AuthorizationEvent(
        account_id=account_id,
        channel_id=channel_id,
        device_id=device_id,
        oauth_grant_id=oauth_grant_id,
        event_type=event_type,
        result=result,
        error_code=error_code,
        error_message=error_message,
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(event)
    return event


def _grant_payload(session: Session, grant: OAuthGrant) -> dict[str, object]:
    scopes = list(
        session.scalars(
            select(OAuthGrantScope.scope)
            .where(OAuthGrantScope.grant_id == grant.id)
            .order_by(OAuthGrantScope.scope)
        )
    )
    return {**grant.__dict__, "scopes": scopes}


def register_oauth_grant(
    session: Session, payload: OAuthGrantCreate
) -> dict[str, object]:
    account = _require_account(session, payload.account_id)
    _require_device(session, payload.device_id)
    scopes = sorted({scope.strip() for scope in payload.scopes if scope.strip()})
    if not scopes:
        raise ConflictError("OAuth scope不能为空")
    now = datetime.now(timezone.utc)
    grant = OAuthGrant(
        account_id=payload.account_id,
        provider_subject=payload.provider_subject.strip(),
        credential_ref=payload.credential_ref.strip(),
        status=payload.status,
        token_expires_at=payload.token_expires_at,
        last_refreshed_at=now if payload.status == "active" else None,
    )
    session.add(grant)
    try:
        session.flush()
        session.add_all(
            [OAuthGrantScope(grant_id=grant.id, scope=scope, created_at=now) for scope in scopes]
        )
        if payload.status == "active":
            account.authorization_status = "authorized"
            account.authorized_at = account.authorized_at or now
            account.last_verified_at = now
        _authorization_event(
            session,
            event_type="oauth_grant_registered",
            result="success",
            account_id=account.id,
            device_id=payload.device_id,
            oauth_grant_id=grant.id,
        )
        _audit(session, "oauth_grant.registered", "oauth_grant", grant.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该Google账号的OAuth授权记录已经存在") from exc
    session.refresh(grant)
    return _grant_payload(session, grant)


def list_oauth_grants(
    session: Session, account_id: str | None = None
) -> list[dict[str, object]]:
    if account_id is not None:
        _require_account(session, account_id)
    statement = select(OAuthGrant)
    if account_id is not None:
        statement = statement.where(OAuthGrant.account_id == account_id)
    grants = list(session.scalars(statement.order_by(OAuthGrant.created_at.desc())))
    return [_grant_payload(session, grant) for grant in grants]


def verify_channel_authorization(
    session: Session, payload: ChannelAuthorizationVerify
) -> AccountChannelAuthorization:
    account = _require_account(session, payload.account_id)
    channel = _require_channel(session, payload.channel_id)
    _require_device(session, payload.device_id)
    grant = session.get(OAuthGrant, payload.oauth_grant_id)
    if grant is None:
        raise IdentityNotFoundError("OAuth授权记录不存在")
    if grant.account_id != account.id:
        raise ConflictError("OAuth授权记录不属于指定Google账号")
    if grant.status != "active":
        raise ConflictError("OAuth授权记录不是可用状态")
    now = datetime.now(timezone.utc)
    if payload.verified_youtube_channel_id != channel.youtube_channel_id:
        _authorization_event(
            session,
            event_type="channel_binding_verified",
            result="failure",
            account_id=account.id,
            channel_id=channel.id,
            device_id=payload.device_id,
            oauth_grant_id=grant.id,
            error_code="youtube_channel_id_mismatch",
            error_message="Token返回的YouTube频道ID与目标频道不一致",
        )
        session.commit()
        raise ConflictError("Token返回的YouTube频道ID与绑定频道不一致，已拒绝绑定")
    binding = session.scalar(
        select(AccountChannelAuthorization)
        .where(
            AccountChannelAuthorization.account_id == account.id,
            AccountChannelAuthorization.channel_id == channel.id,
        )
        .with_for_update()
    )
    if binding is None:
        binding = AccountChannelAuthorization(
            account_id=account.id,
            channel_id=channel.id,
            oauth_grant_id=grant.id,
            status="active",
            verified_youtube_channel_id=payload.verified_youtube_channel_id,
            verified_at=now,
        )
        session.add(binding)
    else:
        binding.oauth_grant_id = grant.id
        binding.status = "active"
        binding.verified_youtube_channel_id = payload.verified_youtube_channel_id
        binding.verified_at = now
        binding.revoked_at = None
    account.last_verified_at = now
    if channel.status == "new":
        channel.status = "authorized"
    try:
        session.flush()
        _authorization_event(
            session,
            event_type="channel_binding_verified",
            result="success",
            account_id=account.id,
            channel_id=channel.id,
            device_id=payload.device_id,
            oauth_grant_id=grant.id,
        )
        _audit(session, "channel_authorization.verified", "channel_authorization", binding.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("频道授权绑定数据冲突") from exc
    session.refresh(binding)
    return binding


def list_channel_authorizations(
    session: Session, channel_id: str
) -> list[AccountChannelAuthorization]:
    _require_channel(session, channel_id)
    return list(
        session.scalars(
            select(AccountChannelAuthorization)
            .where(AccountChannelAuthorization.channel_id == channel_id)
            .order_by(AccountChannelAuthorization.verified_at.desc())
        )
    )


def list_authorization_events(
    session: Session,
    *,
    account_id: str | None = None,
    channel_id: str | None = None,
    result: str | None = None,
) -> list[AuthorizationEvent]:
    statement = select(AuthorizationEvent)
    if account_id is not None:
        statement = statement.where(AuthorizationEvent.account_id == account_id)
    if channel_id is not None:
        statement = statement.where(AuthorizationEvent.channel_id == channel_id)
    if result is not None:
        statement = statement.where(AuthorizationEvent.result == result)
    return list(session.scalars(statement.order_by(AuthorizationEvent.occurred_at.desc())))
