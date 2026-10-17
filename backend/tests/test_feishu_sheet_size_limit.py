import re
from urllib.parse import unquote

import pytest

from zhiju.services.feishu_sync import FeishuClient, FeishuSyncError


def test_large_sheet_read_preserves_rows_across_size_retries_and_blank_pages(monkeypatch):
    client = FeishuClient("app", "secret")
    matrix = [["作品名称", "剧情档案"]] + [[] for _ in range(1499)]
    matrix[1] = ["第一部", "第一部档案"]
    matrix[700] = ["第二部", "第二部档案"]
    matrix[1499] = ["末尾剧目", "末尾档案"]

    def request(method, path, **kwargs):
        match = re.search(r"!A(\d+):J(\d+)", unquote(path))
        start, end = map(int, match.groups())
        if end - start + 1 > 200:
            raise FeishuSyncError("飞书接口失败：data exceeded 10485760 bytes")
        values = matrix[start - 1:end]
        while values and not values[-1]:
            values = values[:-1]
        return {"data": {"valueRange": {"values": values}}}

    monkeypatch.setattr(client, "_request", request)
    rows = client._rows_from_sheet("token", "spreadsheet", "sheet", "J")
    assert rows == [
        {"作品名称": "第一部", "剧情档案": "第一部档案", "__source_row_number": "2"},
        {"作品名称": "第二部", "剧情档案": "第二部档案", "__source_row_number": "701"},
        {"作品名称": "末尾剧目", "剧情档案": "末尾档案", "__source_row_number": "1500"},
    ]


def test_non_size_error_is_not_retried(monkeypatch):
    client = FeishuClient("app", "secret")
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        raise FeishuSyncError("飞书接口失败：permission denied")

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(FeishuSyncError, match="permission denied"):
        client._rows_from_sheet("token", "spreadsheet", "sheet", "J")
    assert len(calls) == 1


def test_single_oversize_row_is_reported_without_infinite_retry(monkeypatch):
    client = FeishuClient("app", "secret")

    def request(*args, **kwargs):
        raise FeishuSyncError("飞书接口失败：data exceeded 10485760 bytes")

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(FeishuSyncError, match="data exceeded"):
        client._rows_from_sheet("token", "spreadsheet", "sheet", "J")
