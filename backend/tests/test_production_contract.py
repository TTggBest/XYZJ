from fastapi.testclient import TestClient
from types import SimpleNamespace

from zhiju.app import app
from zhiju.services.production import NODE_SEQUENCE, summarize_node_progress


def test_production_nodes_run_without_intermediate_review() -> None:
    assert NODE_SEQUENCE == ("search", "title", "cover", "description", "community", "merge")
    assert "review" not in NODE_SEQUENCE
    assert NODE_SEQUENCE[-1] == "merge"


def test_production_api_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v3/tasks" in paths
    assert "/api/v3/tasks/overview" in paths
    assert "/api/v3/tasks/{task_id}/dispatch" in paths
    assert "/api/v3/work-orders/overview" in paths
    assert "/api/v3/work-orders/{work_order_id}" in paths
    assert "/api/v3/work-orders/{work_order_id}/nodes/{node_type}/start" in paths
    assert "/api/v3/work-orders/{work_order_id}/nodes/{node_type}/finish" in paths
    assert "/api/v3/work-orders/{work_order_id}/nodes/{node_type}/retry" in paths
    assert "/api/v3/packages/{package_id}/review" in paths
    assert "/api/v3/packages/operations-overview" in paths
    assert "/api/v3/packages/{package_id}/copy-progress" in paths
    assert "/api/v3/packages/{package_id}/outputs" in paths
    assert "/api/v3/packages/{package_id}/outputs/titles" in paths
    assert "/api/v3/packages/{package_id}/outputs/covers" in paths
    assert "/api/v3/packages/{package_id}/outputs/description" in paths
    assert "/api/v3/packages/{package_id}/outputs/community" in paths
    assert "/api/v3/packages/{package_id}/validations" in paths
    assert "/api/v3/packages/{package_id}/similarity-checks" in paths
    assert (
        "/api/v3/packages/{package_id}/similarity-checks/{compared_package_id}"
        in paths
    )
    assert "/api/v3/packages/{package_id}/merge" in paths


def test_package_operations_overview_exposes_copyable_modules() -> None:
    openapi = TestClient(app).get("/openapi.json").json()
    schema = openapi["components"]["schemas"]["PackageOperationOverview"]

    assert {
        "package_id",
        "work_order_id",
        "production_date",
        "target_publish_date",
        "channel_name",
        "channel_original_name",
        "chinese_title",
        "drama_code",
        "drama_number",
        "business_drama_id",
        "source_row_number",
        "batch_number",
        "youtube_video_id",
        "video_url",
        "planned_local_time",
        "playlist_name",
        "titles",
        "covers",
        "description",
        "community_posts",
        "copy_status",
        "copied_keys",
        "copied_count",
        "copy_total",
        "source_complete",
        "source_incomplete_reason",
    } <= set(schema["properties"])


def test_task_and_work_order_overviews_expose_feishu_row_number() -> None:
    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]

    assert "source_row_number" in schemas["TaskOverview"]["properties"]
    assert "source_row_number" in schemas["WorkOrderOverview"]["properties"]


def test_package_community_cell_exposes_planned_time() -> None:
    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]

    assert "planned_time" in schemas["PackageCommunityCell"]["properties"]


def test_copy_progress_contract_tracks_current_output_ids() -> None:
    openapi = TestClient(app).get("/openapi.json").json()
    mark = openapi["components"]["schemas"]["PackageCopyMark"]
    progress = openapi["components"]["schemas"]["PackageCopyProgress"]

    assert {"output_type", "output_id"} <= set(mark["properties"])
    assert {"package_id", "copy_status", "copied_keys", "copied_count", "copy_total"} <= set(progress["properties"])


def test_work_order_progress_uses_latest_node_states() -> None:
    nodes = [
        SimpleNamespace(node_type="search", status="completed", attempt_number=1),
        SimpleNamespace(node_type="title", status="completed", attempt_number=2),
        SimpleNamespace(node_type="cover", status="running", attempt_number=1),
        SimpleNamespace(node_type="description", status="pending", attempt_number=1),
        SimpleNamespace(node_type="community", status="pending", attempt_number=1),
        SimpleNamespace(node_type="merge", status="pending", attempt_number=1),
    ]

    summary = summarize_node_progress(nodes)

    assert summary["completed_nodes"] == 2
    assert summary["total_nodes"] == 6
    assert summary["progress_percent"] == 33
    assert summary["current_node"] == "cover"
