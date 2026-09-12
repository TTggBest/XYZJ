"""Tenant object names and the sole read adapter for existing local files.

Physical object storage and expiry are implemented in Phase 3. New local
outputs already use the same tenant object keys.
"""
from pathlib import Path

from fastapi import HTTPException

DEFAULT_EXISTING_TENANT_ID = "00000000-0000-4000-8000-000000000001"


def tenant_object_prefix(tenant_id: str) -> str:
    if not tenant_id or tenant_id in {".", ".."} or "/" in tenant_id or "\\" in tenant_id:
        raise HTTPException(status_code=404, detail="数据不存在")
    return f"tenants/{tenant_id}/"


def require_tenant_storage_key(tenant_id: str, key: str) -> str:
    prefix = tenant_object_prefix(tenant_id)
    if not key.startswith(prefix) or "\\" in key or any(part in {"", ".", ".."} for part in key.split("/")):
        raise HTTPException(status_code=404, detail="数据不存在")
    return key


def legacy_local_path(tenant_id: str, key: str, root: Path | None = None) -> Path:
    """Read old default-tenant paths only; never use this for a new write key."""
    if tenant_id != DEFAULT_EXISTING_TENANT_ID or key.startswith("tenants/"):
        raise HTTPException(status_code=404, detail="数据不存在")
    path = Path(key).expanduser()
    if not path.is_absolute() and root is None:
        raise ValueError("相对图片目录需要当前设备配置 ZHJ_SHARED_ROOT")
    path = ((root / path) if root is not None else path).resolve()
    if root is not None and not path.is_relative_to(root.resolve()):
        raise HTTPException(status_code=404, detail="数据不存在")
    return path


def resolve_tenant_storage_path(tenant_id: str, key: str, root: Path) -> Path:
    if not key.startswith("tenants/"):
        return legacy_local_path(tenant_id, key, root)
    key = require_tenant_storage_key(tenant_id, key)
    path = (root / key).resolve()
    if not path.is_relative_to((root / tenant_object_prefix(tenant_id)).resolve()):
        raise HTTPException(status_code=404, detail="数据不存在")
    return path
