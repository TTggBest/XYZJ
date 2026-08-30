from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models import Drama, DramaProductionState
from zhiju.services.identity import _audit
from zhiju.services.operations import normalize_drama_title


ZHIHE_NODE_FIELDS = {
    "parameter_normalization": "parameter_normalization_status",
    "youtube_upload": "youtube_upload_status",
    "copyright_verification": "copyright_verification_status",
    "subtitle_extraction": "subtitle_extraction_status",
    "guishou_upload": "guishou_upload_status",
    "role_extraction": "role_extraction_status",
    "tts": "tts_status",
    "production_completion": "production_completion_status",
}


class ZhiheProgressSource(Protocol):
    def iter_progress_items(self, **kwargs: object): ...


class ZhiheApiError(Exception):
    pass


class ZhiheProgressClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        opener=urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = opener

    def _get(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        query = urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with self.opener(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ZhiheApiError(f"智核接口返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ZhiheApiError(f"智核接口请求失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise ZhiheApiError("智核接口响应不是 JSON 对象")
        return payload

    def iter_progress_items(self, *, updated_after: datetime | None = None):
        params: dict[str, object] = {"limit": 500}
        if updated_after is not None:
            value = updated_after
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            params["updated_after"] = value.isoformat()
        while True:
            page = self._get("/api/v1/dramas/production-progress", params)
            items = page.get("items")
            if not isinstance(items, list):
                raise ZhiheApiError("智核进度列表缺少 items")
            yield from items
            if not page.get("has_more"):
                return
            cursor = page.get("next_cursor")
            if not cursor:
                raise ZhiheApiError("智核进度分页缺少 next_cursor")
            params = {"limit": 500, "cursor": cursor}

    def get_progress(self, drama_id: str) -> dict[str, object]:
        return self._get(
            f"/api/v1/dramas/{quote(drama_id, safe='')}/production-progress"
        )


def _utc_naive(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _find_drama(
    session: Session,
    *,
    source_external_id: str,
    chinese_title: str,
) -> Drama | None:
    mapped = session.scalar(
        select(Drama)
        .join(DramaProductionState, DramaProductionState.drama_id == Drama.id)
        .where(DramaProductionState.source_external_id == source_external_id)
    )
    if mapped is not None:
        return mapped

    matches = list(
        session.scalars(
            select(Drama)
            .where(Drama.normalized_title == normalize_drama_title(chinese_title))
            .limit(2)
        )
    )
    if len(matches) != 1:
        return None
    existing_state = session.scalar(
        select(DramaProductionState).where(
            DramaProductionState.drama_id == matches[0].id
        )
    )
    if (
        existing_state is not None
        and existing_state.source_external_id is not None
        and existing_state.source_external_id != source_external_id
    ):
        return None
    return matches[0]


def _failure_summary(nodes: dict[str, dict[str, object]]) -> str | None:
    failures = []
    labels = {
        "parameter_normalization": "统一参数",
        "youtube_upload": "上传 YouTube",
        "copyright_verification": "版权验证",
        "subtitle_extraction": "字幕提取",
        "guishou_upload": "鬼手上传",
        "role_extraction": "角色提取",
        "tts": "TTS",
        "production_completion": "制作完成",
    }
    for name in ZHIHE_NODE_FIELDS:
        node = nodes[name]
        reason = node.get("failure_reason")
        if node.get("status") == "failed" and reason:
            failures.append(f"{labels[name]}：{reason}")
    return "\n".join(failures) or None


def sync_zhihe_progress(
    session: Session,
    client: ZhiheProgressSource,
    *,
    updated_after: datetime | None = None,
) -> dict[str, int]:
    result = {
        "fetched": 0,
        "updated": 0,
        "skipped_stale": 0,
        "skipped_unmatched": 0,
    }
    synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for item in client.iter_progress_items(updated_after=updated_after):
        result["fetched"] += 1
        drama = _find_drama(
            session,
            source_external_id=str(item["drama_id"]),
            chinese_title=str(item["chinese_title"]),
        )
        if drama is None:
            result["skipped_unmatched"] += 1
            continue

        state = session.scalar(
            select(DramaProductionState).where(DramaProductionState.drama_id == drama.id)
        )
        source_updated_at = _utc_naive(str(item["updated_at"]))
        if (
            state is not None
            and state.source_updated_at is not None
            and state.source_updated_at >= source_updated_at
        ):
            result["skipped_stale"] += 1
            continue
        if state is None:
            state = DramaProductionState(drama_id=drama.id)
            session.add(state)

        nodes = item["nodes"]
        for node_name, field_name in ZHIHE_NODE_FIELDS.items():
            setattr(state, field_name, str(nodes[node_name]["status"]))
        state.episode_count = item.get("episode_count")
        state.total_duration_seconds = item.get("total_duration_seconds")
        state.last_error = _failure_summary(nodes)
        state.source_type = "zhihe"
        state.source_external_id = str(item["drama_id"])
        state.source_updated_at = source_updated_at
        state.source_synced_at = synced_at
        _audit(session, "drama.zhihe_progress_synced", "drama", drama.id)
        result["updated"] += 1

    session.commit()
    return result
