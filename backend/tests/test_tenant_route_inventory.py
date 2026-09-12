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
