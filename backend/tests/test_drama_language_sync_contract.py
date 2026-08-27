from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.services import feishu_sync


LANGUAGE_NAMES = [
    "印地语 Hindi",
    "孟加拉语 Bengali",
    "印尼语 Indonesian",
    "菲律宾语 Filipino / Tagalog",
    "西班牙语 Spanish",
    "葡萄牙语 Brazilian Portuguese",
    "土耳其语 Turkish",
    "阿拉伯语 Arabic",
    "英语 English",
    "俄语 Russian",
    "泰语 Thai",
    "越南语 Vietnamese",
    "法语 French",
    "马来语 Malay",
    "德语 German",
    "乌尔都语 Urdu",
    "意大利语 Italian",
    "韩语 Korean",
    "日语 Japanese",
    "波兰语 Polish",
    "希腊语",
]


def _matrix() -> list[list[str]]:
    tiers = ["作品名称", "状态", "优先级", *(["S"] * 6), *(["A"] * 6), *(["B"] * 6), *(["C"] * 3)]
    languages = ["", "", "批次", *LANGUAGE_NAMES]
    return [
        tiers,
        languages,
        ["测试剧", "制作", "第1批", "1", "1", *([""] * 19)],
    ]


def test_language_matrix_parser_reads_priority_and_coverage() -> None:
    parser = getattr(feishu_sync, "parse_language_matrix", None)

    assert callable(parser)
    payload = parser(_matrix())
    assert len(payload["languages"]) == 21
    assert payload["languages"][0] == {
        "code": "hi",
        "name_zh": "印地语",
        "native_name": "Hindi",
        "priority_tier": "S",
    }
    assert payload["languages"][-1]["code"] == "el"
    assert payload["languages"][-1]["priority_tier"] == "C"
    assert payload["dramas"][0]["chinese_title"] == "测试剧"
    assert payload["dramas"][0]["covered_codes"] == {"hi", "bn"}


def test_language_matrix_parser_rejects_unknown_language() -> None:
    matrix = _matrix()
    matrix[1][-1] = "未知语言 Unknown"

    try:
        feishu_sync.parse_language_matrix(matrix)
    except feishu_sync.FeishuSyncError as exc:
        assert "未知语言" in str(exc)
    else:
        raise AssertionError("未知语言必须拒绝同步")


def test_language_sync_route_and_raw_matrix_reader_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert callable(getattr(feishu_sync.FeishuClient, "matrix_by_title", None))
    assert "post" in paths["/api/v3/feishu-sync/drama-languages"]


def test_language_sync_implementation_preserves_manual_coverages() -> None:
    source = __import__("pathlib").Path(feishu_sync.__file__).read_text(encoding="utf-8")

    assert 'translation.source_type == "feishu"' in source
    assert 'translation.source_type == "manual"' in source
