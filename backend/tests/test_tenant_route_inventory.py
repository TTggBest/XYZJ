from zhiju.app import app
from zhiju.tenant_scope import (
    INTERNAL_ROUTES,
    PLATFORM_ROUTES,
    PUBLIC_ROUTES,
    TENANT_ROUTES,
)


def pairwise_intersections(*scopes: frozenset[tuple[str, str]]) -> set[tuple[str, str]]:
    overlaps: set[tuple[str, str]] = set()
    for index, scope in enumerate(scopes):
        for other_scope in scopes[index + 1 :]:
            overlaps.update(scope & other_scope)
    return overlaps


def api_route_keys() -> set[tuple[str, str]]:
    # FastAPI keeps included routers lazy in the installed version. Its OpenAPI
    # document is the framework's public, fully-expanded route inventory.
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/v3/")
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }


def test_every_api_route_has_exactly_one_scope() -> None:
    actual = api_route_keys()
    classified = PUBLIC_ROUTES | TENANT_ROUTES | PLATFORM_ROUTES | INTERNAL_ROUTES

    assert actual == classified
    assert not pairwise_intersections(
        PUBLIC_ROUTES,
        TENANT_ROUTES,
        PLATFORM_ROUTES,
        INTERNAL_ROUTES,
    )


def test_route_scopes_keep_tenant_business_data_and_platform_catalog_writes_separate() -> None:
    tenant_business_routes = {
        ("DELETE", "/api/v3/demo-data/feishu-first20"),
        ("GET", "/api/v3/audit-events"),
        ("GET", "/api/v3/authorization-events"),
        ("GET", "/api/v3/integration-accounts/{account_id}/credentials"),
        ("PUT", "/api/v3/integration-accounts/{account_id}/credentials"),
        ("POST", "/api/v3/integration-accounts/{account_id}/verify"),
        ("GET", "/api/v3/integrations/{integration_id}/accounts"),
        ("POST", "/api/v3/integrations/{integration_id}/accounts"),
        ("GET", "/api/v3/settings/channel-drama-types"),
        ("PUT", "/api/v3/settings/channel-drama-types/{type_id}"),
        ("GET", "/api/v3/settings/channel-initialization-rules"),
        ("GET", "/api/v3/settings/image-workspace"),
        ("PUT", "/api/v3/settings/image-workspace"),
        ("POST", "/api/v3/feishu-sync/channel-schedules"),
        ("POST", "/api/v3/feishu-sync/channels"),
        ("POST", "/api/v3/feishu-sync/drama-languages"),
        ("POST", "/api/v3/feishu-sync/dramas"),
        ("POST", "/api/v3/feishu-sync/operation-packages"),
        ("POST", "/api/v3/feishu-sync/work-orders"),
        ("POST", "/api/v3/integrations/zhihe/drama-progress/sync"),
        ("GET", "/api/v3/system-events"),
    }
    platform_catalog_writes = {
        ("POST", "/api/v3/languages"),
        ("PUT", "/api/v3/cadence-templates/{daily_publish_count}"),
    }

    assert tenant_business_routes <= TENANT_ROUTES
    assert not tenant_business_routes & PLATFORM_ROUTES
    assert platform_catalog_writes <= PLATFORM_ROUTES
    assert not platform_catalog_writes & TENANT_ROUTES


def test_callback_and_event_publish_keep_their_explicit_non_tenant_scopes() -> None:
    callback = ("GET", "/api/v3/youtube/oauth/callback")
    event_publish = ("POST", "/api/v3/events/publish")

    assert callback in PUBLIC_ROUTES
    assert callback not in TENANT_ROUTES | PLATFORM_ROUTES | INTERNAL_ROUTES
    assert event_publish in INTERNAL_ROUTES
    assert event_publish not in PUBLIC_ROUTES | TENANT_ROUTES | PLATFORM_ROUTES
