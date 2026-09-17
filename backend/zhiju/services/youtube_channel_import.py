from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal
from zhiju.models import (
    AccountChannelAuthorization,
    AuthorizationEvent,
    Channel,
    GoogleAccount,
    OAuthGrant,
    OAuthGrantScope,
    YouTubeChannelImportCandidate,
    YouTubeChannelImportSession,
)
from zhiju.models.base import new_id
from zhiju.services.country_catalog import get_country_option
from zhiju.services.identity import ConflictError
from zhiju.services.youtube_oauth import YOUTUBE_OAUTH_SCOPES, parse_youtube_channel_candidates


class TokenSecretStore(Protocol):
    def put(self, grant_id: str, token: Mapping[str, object]) -> str: ...
    def get(self, grant_id: str) -> dict[str, object] | None: ...


@dataclass(frozen=True)
class ChannelImportSelection:
    candidate_id: str
    target_country_code: str
    default_genre: str
    operational_name: str | None = None
    default_language: str | None = None
    timezone: str | None = None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _require_context(principal: Principal) -> tuple[str, str]:
    if not principal.tenant_id:
        raise ValueError("请先选择当前主账号")
    if not principal.session_id:
        raise ValueError("当前登录会话缺少YouTube授权上下文")
    if "channel.manage" not in principal.permissions and principal.platform_role != "super_admin":
        raise PermissionError("没有频道管理权限")
    return principal.tenant_id, principal.session_id


def create_channel_import_state(
    session: Session,
    principal: Principal,
    *,
    now: datetime | None = None,
    ttl_seconds: int = 600,
) -> str:
    tenant_id, auth_session_id = _require_context(principal)
    current_time = now or datetime.now(timezone.utc)
    opaque_state = secrets.token_urlsafe(32)
    session.add(YouTubeChannelImportSession(
        tenant_id=tenant_id,
        user_id=principal.user_id,
        auth_session_id=auth_session_id,
        opaque_state=opaque_state,
        status="pending_oauth",
        expires_at=current_time + timedelta(seconds=ttl_seconds),
    ))
    session.commit()
    return opaque_state


def complete_channel_import_oauth(
    session: Session,
    secret_store: TokenSecretStore,
    *,
    opaque_state: str,
    identity: Mapping[str, object],
    token: Mapping[str, object],
    youtube_payload: Mapping[str, object],
    now: datetime | None = None,
) -> str:
    current_time = now or datetime.now(timezone.utc)
    import_session = session.scalar(select(YouTubeChannelImportSession).where(
        YouTubeChannelImportSession.opaque_state == opaque_state,
    ))
    if import_session is None or import_session.status != "pending_oauth":
        raise ValueError("授权状态无效或已经使用")
    if _utc(import_session.expires_at) < current_time:
        import_session.status = "expired"
        session.commit()
        raise ValueError("授权状态已过期，请重新发起授权")

    candidates = parse_youtube_channel_candidates(youtube_payload)
    if not candidates:
        raise ValueError("该Google账号没有可管理的YouTube频道")
    subject = str(identity.get("sub") or "").strip()
    email = str(identity.get("email") or "").strip().lower()
    if not subject or not email:
        raise ValueError("Google账号身份信息不完整")
    saved_token = dict(token)

    tenant_id = str(import_session.tenant_id)
    account = session.scalar(select(GoogleAccount).where(
        GoogleAccount.tenant_id == tenant_id,
        GoogleAccount.google_email == email,
    ))
    if account is None:
        account = GoogleAccount(
            id=new_id(), tenant_id=tenant_id,
            nickname=str(identity.get("name") or email).strip()[:120],
            google_email=email, status="active", authorization_status="authorized",
            authorized_at=current_time, last_verified_at=current_time,
        )
        session.add(account)
        session.flush()
    else:
        account.status = "active"
        account.authorization_status = "authorized"
        account.authorized_at = account.authorized_at or current_time
        account.last_verified_at = current_time

    grant = session.scalar(select(OAuthGrant).where(
        OAuthGrant.tenant_id == tenant_id,
        OAuthGrant.account_id == account.id,
        OAuthGrant.provider_subject == subject,
    ))
    if grant is None:
        grant = OAuthGrant(
            id=new_id(), tenant_id=tenant_id, account_id=account.id,
            provider_subject=subject, credential_ref="pending", status="pending",
        )
        session.add(grant)
        session.flush()

    previous_token = secret_store.get(grant.id)
    if not saved_token.get("refresh_token") and previous_token:
        saved_token["refresh_token"] = previous_token.get("refresh_token")
    if not saved_token.get("refresh_token"):
        raise ValueError("Google未返回刷新令牌，请重新授权并允许离线访问")
    grant.credential_ref = secret_store.put(grant.id, saved_token)
    grant.status = "active"
    expires_in = int(saved_token.get("expires_in") or 0)
    grant.token_expires_at = current_time + timedelta(seconds=expires_in) if expires_in else None
    grant.last_refreshed_at = current_time
    grant.revoked_at = None

    session.execute(delete(OAuthGrantScope).where(OAuthGrantScope.grant_id == grant.id))
    scope_value = str(saved_token.get("scope") or "").strip()
    scopes = sorted(set(scope_value.split()) if scope_value else set(YOUTUBE_OAUTH_SCOPES))
    session.add_all(
        OAuthGrantScope(tenant_id=tenant_id, grant_id=grant.id, scope=scope, created_at=current_time)
        for scope in scopes
    )
    session.execute(delete(YouTubeChannelImportCandidate).where(
        YouTubeChannelImportCandidate.import_session_id == import_session.id,
    ))
    session.add_all(
        YouTubeChannelImportCandidate(
            tenant_id=tenant_id,
            import_session_id=import_session.id,
            **candidate,
        )
        for candidate in candidates
    )
    import_session.oauth_grant_id = grant.id
    import_session.status = "ready"
    import_session.consumed_at = current_time
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该Google账号无法在当前主账号授权") from exc
    return import_session.id


def get_channel_import(
    session: Session,
    principal: Principal,
    import_session_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    tenant_id, auth_session_id = _require_context(principal)
    row = session.scalar(select(YouTubeChannelImportSession).where(
        YouTubeChannelImportSession.id == import_session_id,
        YouTubeChannelImportSession.tenant_id == tenant_id,
        YouTubeChannelImportSession.user_id == principal.user_id,
        YouTubeChannelImportSession.auth_session_id == auth_session_id,
    ))
    if row is None:
        raise ValueError("频道导入会话不存在")
    current_time = now or datetime.now(timezone.utc)
    if _utc(row.expires_at) < current_time:
        raise ValueError("频道导入会话已过期")
    candidates = list(session.scalars(select(YouTubeChannelImportCandidate).where(
        YouTubeChannelImportCandidate.tenant_id == tenant_id,
        YouTubeChannelImportCandidate.import_session_id == row.id,
    ).order_by(YouTubeChannelImportCandidate.created_at, YouTubeChannelImportCandidate.id)))
    return {"session": row, "candidates": candidates}


def commit_channel_import(
    session: Session,
    principal: Principal,
    import_session_id: str,
    selections: list[ChannelImportSelection],
    *,
    now: datetime | None = None,
) -> list[Channel]:
    if not selections:
        raise ValueError("请至少选择一个YouTube频道")
    current_time = now or datetime.now(timezone.utc)
    import_data = get_channel_import(
        session, principal, import_session_id, now=current_time,
    )
    import_session = import_data["session"]
    if not isinstance(import_session, YouTubeChannelImportSession) or import_session.status != "ready":
        raise ValueError("频道导入会话当前不可提交")
    tenant_id = str(principal.tenant_id)
    candidates = {candidate.id: candidate for candidate in import_data["candidates"]}
    selected_ids = [selection.candidate_id for selection in selections]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("不能重复选择同一个YouTube频道")
    if any(candidate_id not in candidates for candidate_id in selected_ids):
        raise ValueError("选择的YouTube频道不属于当前导入会话")

    selected_candidates = [candidates[candidate_id] for candidate_id in selected_ids]
    youtube_ids = [candidate.youtube_channel_id for candidate in selected_candidates]
    if session.scalar(select(func.count(Channel.id)).where(
        Channel.youtube_channel_id.in_(youtube_ids),
    )):
        raise ConflictError("该YouTube频道已被绑定")
    if not import_session.oauth_grant_id:
        raise ValueError("频道导入会话缺少Google授权")
    grant = session.scalar(select(OAuthGrant).where(
        OAuthGrant.id == import_session.oauth_grant_id,
        OAuthGrant.tenant_id == tenant_id,
        OAuthGrant.status == "active",
    ))
    if grant is None:
        raise ValueError("Google授权已失效，请重新授权")

    prepared: list[tuple[YouTubeChannelImportCandidate, ChannelImportSelection, object]] = []
    for candidate, selection in zip(selected_candidates, selections, strict=True):
        country = get_country_option(selection.target_country_code)
        if not selection.default_genre.strip():
            raise ValueError("默认题材不能为空")
        prepared.append((candidate, selection, country))

    channels: list[Channel] = []
    for candidate, selection, country in prepared:
        custom_url = candidate.custom_url
        channel_url = (
            f"https://www.youtube.com/{custom_url}"
            if custom_url and custom_url.startswith("@")
            else f"https://www.youtube.com/channel/{candidate.youtube_channel_id}"
        )
        channel = Channel(
            id=new_id(), tenant_id=tenant_id,
            youtube_channel_id=candidate.youtube_channel_id,
            original_name=candidate.title,
            operational_name=(selection.operational_name or "").strip() or None,
            youtube_channel_url=channel_url,
            youtube_avatar_url=candidate.avatar_url,
            country_code=country.code,
            country_name_zh=country.name_zh,
            default_language=(selection.default_language or "").strip() or country.recommended_language,
            default_genre=selection.default_genre.strip(),
            timezone=(selection.timezone or "").strip() or country.recommended_timezone,
            daily_publish_count=0,
            status="authorized",
        )
        session.add(channel)
        session.flush()
        session.add(AccountChannelAuthorization(
            tenant_id=tenant_id,
            account_id=grant.account_id,
            channel_id=channel.id,
            oauth_grant_id=grant.id,
            status="active",
            verified_youtube_channel_id=channel.youtube_channel_id,
            verified_at=current_time,
        ))
        session.add(AuthorizationEvent(
            tenant_id=tenant_id,
            account_id=grant.account_id,
            channel_id=channel.id,
            oauth_grant_id=grant.id,
            event_type="youtube_channel_imported",
            result="success",
            occurred_at=current_time,
        ))
        channels.append(channel)
    import_session.status = "committed"
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该YouTube频道已被绑定") from exc
    for channel in channels:
        session.refresh(channel)
    return channels
