from pathlib import Path

import pytest
from fastapi import HTTPException


def scope():
    from importlib.util import find_spec
    assert find_spec("zhiju.storage_scope") is not None, "tenant storage boundary is missing"
    from zhiju import storage_scope
    return storage_scope


def test_owned_key_keeps_tenant_prefix():
    module = scope()
    assert module.tenant_object_prefix("tenant-a") == "tenants/tenant-a/"
    assert module.require_tenant_storage_key("tenant-a", "tenants/tenant-a/images/a.png") == "tenants/tenant-a/images/a.png"


@pytest.mark.parametrize("key", ["tenants/tenant-b/a.png", "tenants/tenant-ab/a.png",
    "tenants/tenant-a/../tenant-b/a.png", "tenants/tenant-a/x/../../tenant-b/a.png",
    "/tmp/a.png", "old/a.png", "tenants/tenant-a/", "tenants/tenant-a//a.png"])
def test_foreign_or_escaping_new_key_is_404(key):
    with pytest.raises(HTTPException) as exc:
        scope().require_tenant_storage_key("tenant-a", key)
    assert exc.value.status_code == 404


def test_legacy_adapter_only_reads_default_tenant_and_stays_inside_root(tmp_path):
    module = scope()
    default = "00000000-0000-4000-8000-000000000001"
    assert module.resolve_tenant_storage_path(default, "old/a.png", tmp_path) == tmp_path / "old/a.png"
    for tenant, key in [("tenant-a", "old/a.png"), (default, "../outside.png"),
                        (default, "tenants/tenant-b/a.png")]:
        with pytest.raises(HTTPException) as exc:
            module.resolve_tenant_storage_path(tenant, key, tmp_path)
        assert exc.value.status_code == 404


def test_new_key_resolves_under_supplied_root(tmp_path):
    assert scope().resolve_tenant_storage_path("tenant-a", "tenants/tenant-a/a.png", tmp_path) == tmp_path / "tenants/tenant-a/a.png"
