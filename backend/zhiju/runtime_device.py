from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol


class RuntimeDevice(Protocol):
    id: str
    device_key: str
    hostname: str
    device_role: str
    status: str


def normalize_hostname(value: str) -> str:
    hostname = value.strip().lower().rstrip(".")
    if hostname.endswith(".local"):
        hostname = hostname[:-6]
    return hostname


def match_device(devices: Iterable[RuntimeDevice], hostname_candidates: Iterable[str]) -> RuntimeDevice:
    candidates = {normalize_hostname(value) for value in hostname_candidates if value.strip()}
    for device in devices:
        if normalize_hostname(device.hostname) not in candidates:
            continue
        if device.status != "active":
            raise ValueError(f"当前设备 {device.hostname} 未启用，请在设备管理中启用后重试")
        return device
    detected = "、".join(sorted(candidates)) or "未知"
    raise ValueError(f"当前主机 {detected} 未在设备管理中登记")


def runtime_values_for_device(device: RuntimeDevice, *, home: str) -> dict[str, str]:
    if device.device_role not in {"builder", "studio", "worker"}:
        raise ValueError(f"未知设备角色：{device.device_role}")
    if device.device_role == "studio":
        shared_root = Path(home) / "Documents" / "XYData" / "XYZJ"
        host = "0.0.0.0"
        hub_url = ""
    else:
        shared_root = Path("/Volumes/XYData/XYZJ")
        host = "127.0.0.1"
        hub_url = "http://192.168.8.8:19732"
    return {
        "ZHJ_ENV": "production",
        "ZHJ_HOST": host,
        "ZHJ_PORT": "19732",
        "ZHJ_LOG_LEVEL": "INFO",
        "ZHJ_DEVICE_ID": device.id,
        "ZHJ_DEVICE_ROLE": device.device_role,
        "ZHJ_DEVICE_KEY": device.device_key,
        "ZHJ_REALTIME_HUB_URL": hub_url,
        "ZHJ_SHARED_ROOT": str(shared_root),
        "ZHJ_ARTIFACT_ROOT": str(shared_root / "artifacts"),
    }
