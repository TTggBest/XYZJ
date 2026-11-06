"""Regression cases for the recorded V18 title/cover recovery failures."""
from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest

from zhiju.v14_executor.codex import CodexClient
from zhiju.v14_executor.runner import apply_content_recovery


def test_title_reference_repair_keeps_the_complete_three_group_baseline():
    rows = [
        {"index": 1, "title": "First public title", "padding": "kept context " * 700},
        {"index": 2, "title": "Dad signed Mom's assets back... My stepmother couldn't keep them!",
         "title_detail_realization": [{"detail_id": "C03_D1", "disposition": "retain",
                                       "retained_form": "Mom's assets; My stepmother"}]},
        {"index": 3, "title": "Third public title must remain available"},
    ]
    previous = {"section": "title", "results": [{"directions": rows}]}
    frozen = deepcopy(previous)
    data = {"retry_state": [{"node_type": "title", "outcome": "content_error",
                              "error": "v18_title_key_detail_missing_from_title", "result": previous}]}
    stage = SimpleNamespace(prompt="current rules")
    apply_content_recovery(stage, data, "title")
    assert json.dumps(previous, ensure_ascii=False) in stage.prompt
    assert "C03_D1" in stage.prompt and "第2组" in stage.prompt
    assert "连续" in stage.prompt and "retained_form" in stage.prompt
    assert "未受错误影响" in stage.prompt
    assert "仅用于避开旧方案" not in stage.prompt
    assert previous == frozen


@pytest.mark.parametrize("node", ["cover_scene", "cover"])
def test_source_reference_failures_use_the_prior_result_even_after_three_failures(node):
    previous = {"plans": [{"index": 1, "main_action": "Keep the actual relationship",
                            "padding": "source record " * 700},
                           {"index": 3, "source_anchor": "quoted plot fragment"}]}
    failures = [{"node_type": node, "outcome": "content_error",
                 "error": "scene_plan_3_source_anchor_not_in_plot", "result": previous}
                for _ in range(3)]
    stage = SimpleNamespace(prompt="current rules")
    apply_content_recovery(stage, {"retry_state": failures}, node)
    assert json.dumps(previous, ensure_ascii=False) in stage.prompt
    assert "source_anchor" in stage.prompt
    assert "事实" in stage.prompt and "未受错误影响" in stage.prompt
    assert "自动重新规划" not in stage.prompt


def test_recovery_does_not_reopen_a_source_error_resolved_by_the_last_attempt():
    stage = SimpleNamespace(prompt="current rules")
    data = {"retry_state": [
        {"node_type": "cover", "outcome": "content_error",
         "error": "cover_1_source_anchor_not_in_plot; cover_3_source_anchor_not_in_plot", "result": {}},
        {"node_type": "cover", "outcome": "content_error",
         "error": "cover_3_source_anchor_not_in_plot", "result": {"fixed_group_1": True}},
    ]}
    apply_content_recovery(stage, data, "cover")
    assert "cover_3_source_anchor_not_in_plot" in stage.prompt
    assert "cover_1_source_anchor_not_in_plot" not in stage.prompt


@pytest.mark.parametrize("node", ["search", "description", "community_scene", "community"])
def test_other_nodes_keep_the_existing_recovery_text(node):
    previous = {"body": "existing material"}
    stage = SimpleNamespace(prompt="current rules")
    data = {"retry_state": [{"node_type": node, "outcome": "content_error",
                              "error": "existing error", "result": previous}]}
    apply_content_recovery(stage, data, node)
    assert stage.prompt == (
        "current rules\n\n根据以下校验失败原因修正本阶段内容，保持剧情事实、频道定位、固定资产和输出结构不变。"
        "\n最近校验原因：\nexisting error\n上次未通过内容摘录（仅用于避开旧方案）：\n"
        + json.dumps(previous, ensure_ascii=False)
    )


@pytest.mark.parametrize("node", ["search", "title", "cover_scene", "cover"])
def test_inline_creative_calls_have_one_consistent_io_instruction(node):
    stage = SimpleNamespace(node_type=node, prompt="authoritative inline rules", skill_bundle={"version": "V18"})
    prompt = CodexClient().prompt_for(stage)
    assert prompt.endswith(stage.prompt)
    assert "内联" in prompt
    assert "按其中 Skill 的引用读取" not in prompt


def test_other_module_client_prefix_is_unchanged():
    stage = SimpleNamespace(node_type="community", prompt="original community rules", skill_bundle={"version": "V18"})
    assert CodexClient().prompt_for(stage) == (
        "本次选定版本的完整 Skills 文件位于 ./skills/；按其中 Skill 的引用读取配套文件。"
        "智矩控制器负责源数据、状态和输出存储；不要另行操作飞书或 YouTube，也不要启动旧批次。\n\n"
        + stage.prompt
    )


def test_actual_cli_stdin_uses_the_same_inline_prompt(tmp_path):
    from zhiju.workflow_bundles import BASELINE, snapshot
    cli = tmp_path / "capture-codex"
    cli.write_text(f"#!{sys.executable}\n" + """import json,pathlib,sys
args=sys.argv
prompt=sys.stdin.read()
pathlib.Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'actual_stdin':prompt}))
""")
    cli.chmod(0o700)
    stage = SimpleNamespace(node_type="cover", prompt="Do not inspect files. Use these inline rules.",
                            rules={}, schema={}, skill_bundle=snapshot(BASELINE.read_bytes(),
                            version_id="test-inline", label="V14", revision=1))
    client = CodexClient(binary=str(cli))
    result = client.generate(stage, "test-capture")
    assert result["actual_stdin"] == client.prompt_for(stage)
    assert "按其中 Skill 的引用读取" not in result["actual_stdin"]
