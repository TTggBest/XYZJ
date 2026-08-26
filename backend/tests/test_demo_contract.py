from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.schemas.demo import DemoDataImportRequest


def test_demo_data_endpoints_are_exposed() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    path = "/api/v3/demo-data/feishu-first20"
    assert set(paths[path]) >= {"get", "post", "delete"}


def test_demo_import_requires_paired_rows() -> None:
    try:
        DemoDataImportRequest(work_rows=[{"剧名": "测试"}], task_rows=[])
    except ValueError as exc:
        assert "task_rows" in str(exc) or "样本行数" in str(exc)
    else:
        raise AssertionError("不成对的演示数据不应通过校验")
