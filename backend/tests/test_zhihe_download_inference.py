from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from test_drama_progress_filters import add_drama, progress_client
from zhiju.models import DramaProductionState
from zhiju.services.zhihe_progress_sync import sync_zhihe_progress


FOLLOWING_NODES = (
    "parameter_normalization", "youtube_upload", "copyright_verification",
    "subtitle_extraction", "guishou_upload", "role_extraction", "tts",
    "production_completion",
)


def source(statuses, updated_at):
    item = {
        "drama_id": "remote-test", "chinese_title": "测试剧1",
        "updated_at": updated_at, "episode_count": 60,
        "total_duration_seconds": 3600,
        "nodes": {node: {"status": status} for node, status in statuses.items()},
    }
    return SimpleNamespace(iter_progress_items=lambda **_: iter([item]))


@pytest.mark.parametrize("completed_node", FOLLOWING_NODES)
@pytest.mark.parametrize("version", ("new", "same", "older"))
def test_any_completed_following_node_implies_download_completed(progress_client, completed_node, version):
    client, session = progress_client
    statuses = {node: "not_started" for node in FOLLOWING_NODES}
    statuses[completed_node] = "completed"
    saved_statuses = statuses if version != "new" else {node: "not_started" for node in FOLLOWING_NODES}
    drama_id = add_drama(session, 1, **{f"{node}_status": status for node, status in saved_statuses.items()})
    state = session.scalar(select(DramaProductionState).where(DramaProductionState.drama_id == drama_id))
    state.source_external_id = "remote-test"
    state.source_updated_at = datetime(2026, 10, 16, 1)
    session.commit()
    remote_time = {"new": "2026-10-16T02:00:00Z", "same": "2026-10-16T01:00:00Z", "older": "2026-10-16T00:00:00Z"}[version]
    remote_statuses = {node: "not_started" for node in FOLLOWING_NODES} if version == "older" else statuses

    result = sync_zhihe_progress(session, source(remote_statuses, remote_time))
    response = client.get(f"/api/v3/dramas/{drama_id}/production-state")

    assert result == {"fetched": 1, "updated": 1, "skipped_stale": 0, "skipped_unmatched": 0}
    assert response.status_code == 200
    assert response.json()["cloud_download_status"] == "completed"
    for node, status in statuses.items():
        assert response.json()[f"{node}_status"] == status
    # The next sync must neither repeat the repair nor overwrite newer source state.
    assert sync_zhihe_progress(session, source(remote_statuses, remote_time)) == {
        "fetched": 1, "updated": 0, "skipped_stale": 1, "skipped_unmatched": 0,
    }


@pytest.mark.parametrize("status", ("not_started", "in_progress", "failed"))
def test_no_completed_following_node_does_not_infer_download(progress_client, status):
    client, session = progress_client
    drama_id = add_drama(session, 1)
    sync_zhihe_progress(session, source({node: status for node in FOLLOWING_NODES}, "2026-10-16T02:00:00Z"))
    response = client.get(f"/api/v3/dramas/{drama_id}/production-state")
    assert response.status_code == 200
    assert response.json()["cloud_download_status"] == "not_started"
