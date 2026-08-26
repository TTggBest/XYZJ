from types import SimpleNamespace

import pytest

from zhiju.runtime_device import match_device, normalize_hostname, runtime_values_for_device


def device(**overrides):
    values = {
        "id": "device-1",
        "device_key": "fleet:m4-2",
        "hostname": "M4-2.local",
        "device_role": "worker",
        "status": "active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_hostname_matching_ignores_case_and_local_suffix() -> None:
    assert normalize_hostname("M4-2.LOCAL") == "m4-2"
    matched = match_device([device()], ["m4-2", "M4-2.local"])
    assert matched.device_key == "fleet:m4-2"


def test_unknown_or_inactive_device_is_refused() -> None:
    with pytest.raises(ValueError, match="未在设备管理中登记"):
        match_device([device()], ["new-machine"])
    with pytest.raises(ValueError, match="未启用"):
        match_device([device(status="inactive")], ["M4-2"])


def test_runtime_paths_and_sse_are_derived_from_database_role() -> None:
    studio = runtime_values_for_device(device(device_role="studio"), home="/Users/star")
    worker = runtime_values_for_device(device(device_role="worker"), home="/Users/a1")

    assert studio["ZHJ_HOST"] == "0.0.0.0"
    assert studio["ZHJ_SHARED_ROOT"] == "/Users/star/Documents/XYData/XYZJ"
    assert studio["ZHJ_REALTIME_HUB_URL"] == ""
    assert worker["ZHJ_HOST"] == "127.0.0.1"
    assert worker["ZHJ_SHARED_ROOT"] == "/Volumes/XYData/XYZJ"
    assert worker["ZHJ_REALTIME_HUB_URL"] == "http://192.168.8.8:19732"
