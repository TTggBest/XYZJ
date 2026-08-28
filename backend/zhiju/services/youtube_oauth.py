import json
import secrets
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from zhiju.models.base import new_id
from zhiju.models.identity import (
    AccountChannelAuthorization,
    AuthorizationEvent,
    Channel,
    GoogleAccount,
    OAuthGrant,
    OAuthGrantScope,
)


YOUTUBE_OAUTH_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
)

OAUTH_CLIENT_KEYCHAIN_SERVICE = "com.xiaoyu.zhiju.youtube.oauth-client"
OAUTH_CLIENT_KEYCHAIN_ACCOUNT = "default"
OAUTH_CLIENT_CREDENTIAL_REF = (
    f"keychain://{OAUTH_CLIENT_KEYCHAIN_SERVICE}/{OAUTH_CLIENT_KEYCHAIN_ACCOUNT}"
)
OAUTH_TOKEN_KEYCHAIN_SERVICE = "com.xiaoyu.zhiju.youtube.oauth-token"

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class OAuthClientConfig:
    client_type: str
    client_id: str
    client_secret_value: str
    project_id: str | None
    auth_uri: str
    token_uri: str
    redirect_uri: str


@dataclass(frozen=True)
class PendingOAuthState:
    channel_id: str
    expires_at: datetime


class OAuthStateStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = 600,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._states: dict[str, PendingOAuthState] = {}
        self._lock = threading.Lock()

    def create(self, channel_id: str) -> str:
        state = secrets.token_urlsafe(32)
        pending = PendingOAuthState(
            channel_id=channel_id,
            expires_at=self._clock() + timedelta(seconds=self.ttl_seconds),
        )
        with self._lock:
            self._states[state] = pending
        return state

    def consume(self, state: str) -> PendingOAuthState:
        with self._lock:
            pending = self._states.pop(state, None)
        if pending is None:
            raise ValueError("授权状态无效或已经使用")
        if pending.expires_at < self._clock():
            raise ValueError("授权状态已过期，请重新发起授权")
        return pending


class MacOSKeychainSecretStore:
    def __init__(self, runner: CommandRunner = subprocess.run):
        self._runner = runner

    def put(self, service: str, account: str, value: str) -> None:
        result = self._runner(
            [
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-s",
                service,
                "-a",
                account,
                "-w",
                value,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("无法写入macOS钥匙串")

    def get(self, service: str, account: str) -> str | None:
        result = self._runner(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            capture_output=True,
            text=True,
        )
        return result.stdout.rstrip("\n") if result.returncode == 0 else None


def import_oauth_client_file(
    path: Path,
    store: MacOSKeychainSecretStore,
) -> OAuthClientConfig:
    if not path.is_file():
        raise FileNotFoundError("未找到旧版Google OAuth凭证")
    document = path.read_text(encoding="utf-8")
    config = parse_oauth_client_document(document)
    store.put(
        OAUTH_CLIENT_KEYCHAIN_SERVICE,
        OAUTH_CLIENT_KEYCHAIN_ACCOUNT,
        document,
    )
    return config


def oauth_client_status(
    legacy_path: Path,
    store: MacOSKeychainSecretStore,
    *,
    can_manage: bool,
) -> dict[str, object]:
    document = store.get(
        OAUTH_CLIENT_KEYCHAIN_SERVICE,
        OAUTH_CLIENT_KEYCHAIN_ACCOUNT,
    )
    config = parse_oauth_client_document(document) if document else None
    return {
        "configured": config is not None,
        "can_manage": can_manage,
        "client_type": config.client_type if config else None,
        "project_id": config.project_id if config else None,
        "redirect_uri": config.redirect_uri if config else None,
        "credential_ref": OAUTH_CLIENT_CREDENTIAL_REF if config else None,
        "scopes": list(YOUTUBE_OAUTH_SCOPES) if config else [],
        "legacy_file_available": legacy_path.is_file(),
    }


def parse_oauth_client_document(document: str) -> OAuthClientConfig:
    try:
        payload = json.loads(document)
    except json.JSONDecodeError as exc:
        raise ValueError("Google OAuth 凭证不是有效JSON") from exc
    client_type = "web" if "web" in payload else "installed" if "installed" in payload else None
    if client_type is None or not isinstance(payload[client_type], dict):
        raise ValueError("Google OAuth 凭证缺少web或installed配置")
    values = payload[client_type]
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    if any(not values.get(field) for field in required):
        raise ValueError("Google OAuth 凭证字段不完整")
    redirect_uris = values.get("redirect_uris") or []
    if not redirect_uris:
        raise ValueError("Google OAuth 凭证缺少回调地址")
    redirect_uri = next(
        (uri for uri in redirect_uris if uri.startswith("http://127.0.0.1:")),
        redirect_uris[0],
    )
    return OAuthClientConfig(
        client_type=client_type,
        client_id=values["client_id"],
        client_secret_value=values["client_secret"],
        project_id=values.get("project_id"),
        auth_uri=values["auth_uri"],
        token_uri=values["token_uri"],
        redirect_uri=redirect_uri,
    )


def build_authorization_url(config: OAuthClientConfig, state: str) -> str:
    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_OAUTH_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent select_account",
            "state": state,
        }
    )
    return f"{config.auth_uri}?{query}"


def load_oauth_client_config(store: MacOSKeychainSecretStore) -> OAuthClientConfig:
    document = store.get(OAUTH_CLIENT_KEYCHAIN_SERVICE, OAUTH_CLIENT_KEYCHAIN_ACCOUNT)
    if not document:
        raise ValueError("YouTube OAuth 尚未配置，请先在设置中导入旧版凭证")
    return parse_oauth_client_document(document)


def save_oauth_token(
    store: MacOSKeychainSecretStore,
    grant_id: str,
    token: Mapping[str, object],
) -> str:
    store.put(
        OAUTH_TOKEN_KEYCHAIN_SERVICE,
        grant_id,
        json.dumps(dict(token), ensure_ascii=True, separators=(",", ":")),
    )
    return f"keychain://{OAUTH_TOKEN_KEYCHAIN_SERVICE}/{grant_id}"


def load_oauth_token(
    store: MacOSKeychainSecretStore,
    grant_id: str,
) -> dict[str, object] | None:
    document = store.get(OAUTH_TOKEN_KEYCHAIN_SERVICE, grant_id)
    return json.loads(document) if document else None


def exchange_authorization_code(
    config: OAuthClientConfig,
    code: str,
) -> dict[str, object]:
    return _request_json(
        config.token_uri,
        method="POST",
        form={
            "client_id": config.client_id,
            "client_secret": config.client_secret_value,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config.redirect_uri,
        },
    )


def refresh_oauth_access_token(
    config: OAuthClientConfig,
    refresh_token: str,
) -> dict[str, object]:
    return _request_json(
        config.token_uri,
        method="POST",
        form={
            "client_id": config.client_id,
            "client_secret": config.client_secret_value,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )


def fetch_google_identity(access_token: str) -> dict[str, object]:
    return _request_json(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )


def fetch_youtube_channels(access_token: str) -> dict[str, object]:
    return _request_json(
        "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true&maxResults=50",
        headers={"Authorization": f"Bearer {access_token}"},
    )


def choose_youtube_channel(
    payload: Mapping[str, object],
    expected_channel_id: str,
) -> dict[str, object]:
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    channel = next(
        (item for item in items if isinstance(item, dict) and item.get("id") == expected_channel_id),
        None,
    )
    if channel is None:
        raise ValueError("Google授权返回的YouTube频道与目标频道不一致")
    return channel


def youtube_channel_identity(channel_payload: Mapping[str, object]) -> tuple[str | None, str | None]:
    snippet = channel_payload.get("snippet")
    if not isinstance(snippet, dict):
        return None, None
    title = str(snippet.get("title") or "").strip() or None
    thumbnails = snippet.get("thumbnails")
    if not isinstance(thumbnails, dict):
        return title, None
    for size in ("maxres", "standard", "high", "medium", "default"):
        thumbnail = thumbnails.get(size)
        if isinstance(thumbnail, dict):
            url = str(thumbnail.get("url") or "").strip()
            if url:
                return title, url
    return title, None


def _request_json(
    url: str,
    *,
    method: str = "GET",
    form: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    body = urlencode(form).encode("utf-8") if form else None
    request_headers = dict(headers or {})
    if form:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"Google OAuth 请求失败：HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("无法连接Google OAuth服务") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Google OAuth返回了无效数据") from exc
    if not isinstance(payload, dict):
        raise ValueError("Google OAuth返回了无效数据")
    return payload


class OAuthCallbackRelay:
    def __init__(self) -> None:
        self._servers: dict[tuple[str, int], ThreadingHTTPServer] = {}
        self._lock = threading.Lock()

    def ensure(self, registered_uri: str, app_callback_uri: str) -> None:
        registered = urlsplit(registered_uri)
        if registered.scheme != "http" or registered.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("当前Google OAuth回调不是本机HTTP地址")
        host = registered.hostname or "127.0.0.1"
        port = registered.port or 80
        key = (host, port)
        with self._lock:
            if key in self._servers:
                return

            target = app_callback_uri

            class RelayHandler(BaseHTTPRequestHandler):
                def do_GET(self) -> None:
                    query = urlsplit(self.path).query
                    separator = "&" if "?" in target else "?"
                    location = f"{target}{separator}{query}" if query else target
                    self.send_response(302)
                    self.send_header("Location", location)
                    self.end_headers()

                def log_message(self, format: str, *args: object) -> None:
                    return

            try:
                server = ThreadingHTTPServer((host, port), RelayHandler)
            except OSError as exc:
                raise ValueError(f"无法监听Google OAuth回调端口 {port}") from exc
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self._servers[key] = server


def complete_channel_authorization(
    session: Session,
    store: MacOSKeychainSecretStore,
    *,
    channel_id: str,
    identity: Mapping[str, object],
    token: Mapping[str, object],
    youtube_payload: Mapping[str, object],
) -> AccountChannelAuthorization:
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise ValueError("目标频道不存在")
    youtube_channel = choose_youtube_channel(youtube_payload, channel.youtube_channel_id)
    youtube_title, youtube_avatar_url = youtube_channel_identity(youtube_channel)

    subject = str(identity.get("sub") or "").strip()
    email = str(identity.get("email") or "").strip().lower()
    if not subject or not email:
        raise ValueError("Google账号身份信息不完整")

    now = datetime.now(timezone.utc)
    account = session.scalar(select(GoogleAccount).where(GoogleAccount.google_email == email))
    if account is None:
        account = GoogleAccount(
            nickname=str(identity.get("name") or email).strip()[:120],
            google_email=email,
            status="active",
            authorization_status="authorized",
            authorized_at=now,
            last_verified_at=now,
        )
        session.add(account)
        session.flush()
    else:
        account.status = "active"
        account.authorization_status = "authorized"
        account.authorized_at = account.authorized_at or now
        account.last_verified_at = now

    grant = session.scalar(
        select(OAuthGrant).where(
            OAuthGrant.account_id == account.id,
            OAuthGrant.provider_subject == subject,
        )
    )
    if grant is None:
        grant = OAuthGrant(
            id=new_id(),
            account_id=account.id,
            provider_subject=subject,
            credential_ref="pending",
            status="pending",
        )
        session.add(grant)
        session.flush()

    saved_token = dict(token)
    previous_token = load_oauth_token(store, grant.id)
    if not saved_token.get("refresh_token") and previous_token:
        saved_token["refresh_token"] = previous_token.get("refresh_token")
    if not saved_token.get("refresh_token"):
        raise ValueError("Google未返回刷新令牌，请重新授权并允许离线访问")

    grant.credential_ref = save_oauth_token(store, grant.id, saved_token)
    grant.status = "active"
    expires_in = int(saved_token.get("expires_in") or 0)
    grant.token_expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    grant.last_refreshed_at = now
    grant.revoked_at = None

    scope_value = str(saved_token.get("scope") or "").strip()
    scopes = sorted(set(scope_value.split()) if scope_value else set(YOUTUBE_OAUTH_SCOPES))
    session.execute(delete(OAuthGrantScope).where(OAuthGrantScope.grant_id == grant.id))
    session.add_all(
        OAuthGrantScope(grant_id=grant.id, scope=scope, created_at=now)
        for scope in scopes
    )

    binding = session.scalar(
        select(AccountChannelAuthorization).where(
            AccountChannelAuthorization.account_id == account.id,
            AccountChannelAuthorization.channel_id == channel.id,
        )
    )
    if binding is None:
        binding = AccountChannelAuthorization(
            account_id=account.id,
            channel_id=channel.id,
            oauth_grant_id=grant.id,
            status="active",
            verified_youtube_channel_id=channel.youtube_channel_id,
            verified_at=now,
        )
        session.add(binding)
    else:
        binding.oauth_grant_id = grant.id
        binding.status = "active"
        binding.verified_youtube_channel_id = channel.youtube_channel_id
        binding.verified_at = now
        binding.revoked_at = None
    if channel.status == "new":
        channel.status = "authorized"
    if youtube_title:
        channel.original_name = youtube_title
    if youtube_avatar_url:
        channel.youtube_avatar_url = youtube_avatar_url
    session.add(
        AuthorizationEvent(
            account_id=account.id,
            channel_id=channel.id,
            oauth_grant_id=grant.id,
            event_type="youtube_oauth_completed",
            result="success",
            occurred_at=now,
        )
    )
    session.commit()
    session.refresh(binding)
    return binding
