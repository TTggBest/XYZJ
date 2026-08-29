import json
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from zhiju.config import APP_ROOT, get_settings
from zhiju.database import get_db
from zhiju.models.identity import Channel
from zhiju.schemas.operations import PlaylistRead
from zhiju.schemas.youtube_oauth import (
    YouTubeAuthorizationStart,
    YouTubeOAuthClientStatus,
    YouTubeVideoSyncResult,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError
from zhiju.services.youtube_channel_sync import (
    create_authorized_channel_playlist,
    sync_authorized_channel_videos,
)
from zhiju.services.youtube_oauth import (
    MacOSKeychainSecretStore,
    OAuthCallbackRelay,
    OAuthStateStore,
    build_authorization_url,
    complete_channel_authorization,
    exchange_authorization_code,
    fetch_google_identity,
    fetch_youtube_channels,
    import_oauth_client_file,
    load_oauth_client_config,
    oauth_client_status,
)


router = APIRouter(prefix="/v3", tags=["youtube-oauth"])
oauth_states = OAuthStateStore()
callback_relay = OAuthCallbackRelay()


def _legacy_client_path() -> Path:
    candidates = (
        APP_ROOT.parent / "client_secret.json",
        APP_ROOT.parent.parent / "client_secret.json",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


@router.get("/settings/youtube-oauth", response_model=YouTubeOAuthClientStatus)
def get_youtube_oauth_status() -> YouTubeOAuthClientStatus:
    settings = get_settings()
    try:
        return YouTubeOAuthClientStatus.model_validate(
            oauth_client_status(
                _legacy_client_path(),
                MacOSKeychainSecretStore(),
                can_manage=settings.device_role == "builder",
            )
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/settings/youtube-oauth/import-legacy",
    response_model=YouTubeOAuthClientStatus,
)
def post_import_legacy_youtube_oauth() -> YouTubeOAuthClientStatus:
    settings = get_settings()
    if settings.device_role != "builder":
        raise HTTPException(status_code=403, detail="仅代码机可以导入YouTube OAuth凭证")
    path = _legacy_client_path()
    store = MacOSKeychainSecretStore()
    try:
        import_oauth_client_file(path, store)
        return YouTubeOAuthClientStatus.model_validate(
            oauth_client_status(path, store, can_manage=True)
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/channels/{channel_id}/youtube-authorization/start",
    response_model=YouTubeAuthorizationStart,
)
def post_start_youtube_authorization(
    channel_id: str,
    session: Session = Depends(get_db),
) -> YouTubeAuthorizationStart:
    settings = get_settings()
    if settings.device_role != "builder":
        raise HTTPException(status_code=403, detail="仅代码机可以执行YouTube授权")
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="频道不存在")
    store = MacOSKeychainSecretStore()
    try:
        config = load_oauth_client_config(store)
        state = oauth_states.create(channel.id)
        callback_relay.ensure(
            config.redirect_uri,
            f"http://127.0.0.1:{settings.port}/api/v3/youtube/oauth/callback",
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return YouTubeAuthorizationStart(
        authorization_url=build_authorization_url(config, state),
        expires_in_seconds=oauth_states.ttl_seconds,
    )


@router.post(
    "/channels/{channel_id}/youtube-videos/sync",
    response_model=YouTubeVideoSyncResult,
)
def post_sync_youtube_channel_videos(
    channel_id: str,
    session: Session = Depends(get_db),
) -> YouTubeVideoSyncResult:
    settings = get_settings()
    if settings.device_role != "builder":
        raise HTTPException(status_code=403, detail="仅代码机可以执行YouTube视频同步")
    try:
        return YouTubeVideoSyncResult.model_validate(
            sync_authorized_channel_videos(
                session,
                MacOSKeychainSecretStore(),
                channel_id=channel_id,
            )
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConflictError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/channels/{channel_id}/playlists/{playlist_id}/create-youtube",
    response_model=PlaylistRead,
)
def post_create_youtube_playlist(
    channel_id: str,
    playlist_id: str,
    session: Session = Depends(get_db),
) -> PlaylistRead:
    settings = get_settings()
    if settings.device_role != "builder":
        raise HTTPException(status_code=403, detail="仅代码机可以创建YouTube播放列表")
    try:
        return create_authorized_channel_playlist(
            session,
            MacOSKeychainSecretStore(),
            channel_id=channel_id,
            playlist_id=playlist_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConflictError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/youtube/oauth/callback", response_class=HTMLResponse)
def get_youtube_oauth_callback(
    state: str = Query(min_length=1),
    code: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_db),
) -> HTMLResponse:
    settings = get_settings()
    if settings.device_role != "builder":
        return _callback_page(False, "仅代码机可以完成YouTube授权")
    try:
        pending = oauth_states.consume(state)
        if error:
            raise ValueError("Google授权已取消")
        if not code:
            raise ValueError("Google回调缺少授权码")
        store = MacOSKeychainSecretStore()
        config = load_oauth_client_config(store)
        token = exchange_authorization_code(config, code)
        access_token = str(token.get("access_token") or "")
        if not access_token:
            raise ValueError("Google未返回访问令牌")
        identity = fetch_google_identity(access_token)
        youtube_payload = fetch_youtube_channels(access_token)
        complete_channel_authorization(
            session,
            store,
            channel_id=pending.channel_id,
            identity=identity,
            token=token,
            youtube_payload=youtube_payload,
        )
        return _callback_page(True, "YouTube频道授权完成")
    except (RuntimeError, ValueError) as exc:
        session.rollback()
        return _callback_page(False, str(exc))


def _callback_page(success: bool, message: str) -> HTMLResponse:
    event = "youtube-auth-complete" if success else "youtube-auth-failed"
    title = "授权完成" if success else "授权失败"
    safe_message = escape(message)
    script_message = json.dumps(message, ensure_ascii=True)
    return HTMLResponse(
        f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>{title}</title></head>
<body><p>{safe_message}</p><script>
if (window.opener) window.opener.postMessage({{type: \"{event}\", message: {script_message}}}, window.location.origin);
setTimeout(() => window.close(), 500);
</script></body></html>""",
        status_code=200 if success else 400,
    )
