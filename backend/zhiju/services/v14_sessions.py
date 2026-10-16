"""Issue an ordinary device-bound AuthSession, not a second worker identity system."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from zhiju.auth_context import _utc
from zhiju.models import AuthSession, AuthEvent, Device, DeviceUserBinding
from zhiju.security import new_opaque_token, digest_token
from zhiju.services.identity import ConflictError
from zhiju.services.v14_runs import get_settings


def authorize_executor(session, principal):
    setting = get_settings(session)
    if not setting:
        raise ConflictError("请先保存 V14 主机配置")
    host = setting.payload["host_id"]
    now = datetime.now(timezone.utc)
    device = session.get(Device, host)
    binding = session.scalar(select(DeviceUserBinding).where(
        DeviceUserBinding.device_id == host, DeviceUserBinding.user_id == principal.user_id,
        DeviceUserBinding.tenant_id == principal.tenant_id, DeviceUserBinding.status == "active"))
    if not device or device.status != "active" or not binding or (binding.expires_at and _utc(binding.expires_at) <= now):
        raise ConflictError("请先在账号中心将该设备有效绑定到当前用户和公司")
    parent = session.get(AuthSession, principal.session_id) if principal.session_id else None
    if not parent or parent.user_id != principal.user_id or parent.tenant_id != principal.tenant_id or parent.status != "active" or _utc(parent.expires_at) <= now:
        raise ConflictError("当前登录会话已失效，请重新登录")
    expires = min(_utc(parent.expires_at), now + timedelta(hours=8))
    if binding.expires_at:
        expires = min(expires, _utc(binding.expires_at))
    token = new_opaque_token()
    row = AuthSession(user_id=principal.user_id, tenant_id=principal.tenant_id, device_id=host,
        binding_id=binding.id, token_digest=digest_token(token), status="active",
        expires_at=expires, last_seen_at=now, created_at=now)
    session.add(row)
    session.flush()
    session.add(AuthEvent(event_type="login", result="success", actor_user_id=principal.user_id,
        actor_device_id=host, tenant_id=principal.tenant_id, session_id=row.id,
        request_id=str(uuid4()), reason="用户明确授权 V14 本机执行会话", occurred_at=now))
    session.commit()
    return {"session_token": token, "host_id": host, "tenant_id": principal.tenant_id,
            "account_profile": setting.payload["account_profile"], "expires_at": expires.isoformat()}
