from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import Channel
from zhiju.services.channel import get_channel_initialization_readiness


ROOT = Path(__file__).resolve().parents[2]


def test_channel_initialization_readiness_route_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/channels/{channel_id}/initialization-readiness"]


def test_channel_initialization_readiness_reports_missing_channel_inputs() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-INIT-{suffix}",
            original_name=f"频道-{suffix}",
            timezone="Asia/Shanghai",
            status="new",
        )
        session.add(channel)
        session.commit()

        readiness = get_channel_initialization_readiness(session, channel.id)

        assert readiness["can_initialize"] is False
        assert readiness["missing_inputs"] == [
            "频道中文意思",
            "初始题材",
            "短剧类型",
        ]
        assert len(readiness["rules"]) == 11
        assert readiness["missing_rule_modules"] == [
            rule["module_name"]
            for rule in readiness["rules"]
            if rule["readiness"] != "ready"
        ]
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_channel_detail_loads_and_renders_initialization_readiness() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function channelInitializationReadiness" in source
    assert "`/channels/${id}/initialization-readiness`" in source
    assert "初始化准备" in source
    assert "当前不可初始化" in source
