#!/usr/bin/env python3
"""Validate the deterministic structure and GLOBAL boundary of a V2 generation spec."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SECTIONS = ["GLOBAL", "TITLE", "COVER", "DESCRIPTION", "HASHTAG", "COMMUNITY", "PLAYLIST"]
GLOBAL_FIELDS = [
    "正式频道名",
    "目标语言",
    "目标市场",
    "频道性别方向",
    "稳定频道类型",
    "公开内容语言",
    "允许的跨语言表达",
    "频道公共语气",
    "GLOBAL权限声明",
]
PERMISSION = (
    "GLOBAL只确认频道身份、目标语言、目标市场和公共表达环境。"
    "GLOBAL不得替代当前剧情决定人物、事件、身份、冲突、爆点、结果或视觉场景；"
    "当前剧目的具体包装内容只能来自当前剧情事实、对应模块Core及已验收的单剧动态输入。"
)
FORBIDDEN_GLOBAL_PATTERNS = {
    "经营指标": re.compile(r"(?:CTR|点击率|展示量|展示次数|观看时长|观看次数|播放量|留存|订阅(?:增长|变化)|\d+(?:\.\d+)?%)", re.I),
    "时间窗口或阶段策略": re.compile(r"(?:近(?:7|28|90)天|最近(?:7|28|90)天|频道阶段|当前策略|当前优先|近期题材)"),
    "具体剧情或视觉素材": re.compile(r"(?:DNA|双胞胎|CEO|首席执行官|继承人|董事会|会议室|婚礼|复仇|认亲|验亲)", re.I),
    "模块或示例指令": re.compile(r"(?:标题方向|封面方向|标题示例|封面示例|固定钩子|映射规则)"),
}
HEADING_RE = re.compile(r"^## \[([A-Z]+)\]\s*$", re.MULTILINE)
ALL_H2_RE = re.compile(r"^## .+$", re.MULTILINE)
FIELD_RE = re.compile(r"^- ([^：\n]+)：(.*)$", re.MULTILINE)


def validate_text(
    text: str,
    *,
    expected_channel_name: str | None = None,
    expected_language: str | None = None,
    expected_market: str | None = None,
    allow_placeholders: bool = False,
) -> list[str]:
    errors: list[str] = []
    headings = HEADING_RE.findall(text)
    if headings != SECTIONS:
        errors.append(f"章节必须唯一且按固定顺序出现：{', '.join(SECTIONS)}；实际：{', '.join(headings) or '无'}")
    all_h2 = ALL_H2_RE.findall(text)
    expected_h2 = [f"## [{section}]" for section in SECTIONS]
    if all_h2 != expected_h2:
        errors.append("不得出现七个固定标记以外的 H2 章节")

    global_match = re.search(r"^## \[GLOBAL\]\s*$(.*?)(?=^## \[)", text, re.MULTILINE | re.DOTALL)
    if not global_match:
        errors.append("缺少可解析的 GLOBAL 章节")
        return errors

    global_body = global_match.group(1)
    fields = FIELD_RE.findall(global_body)
    field_names = [name.strip() for name, _ in fields]
    if field_names != GLOBAL_FIELDS:
        errors.append(f"GLOBAL字段必须齐全、唯一且顺序固定；实际：{', '.join(field_names) or '无'}")
    nonempty_global_lines = [line.strip() for line in global_body.splitlines() if line.strip()]
    if len(nonempty_global_lines) != len(fields) or any(not line.startswith("- ") for line in nonempty_global_lines):
        errors.append("GLOBAL只能包含九个固定字段，不得添加正文、子标题或其他列表项")

    values = {name.strip(): value.strip() for name, value in fields}
    for field in GLOBAL_FIELDS:
        if not values.get(field):
            errors.append(f"GLOBAL字段为空：{field}")
        elif not allow_placeholders and re.search(r"<[^>]+>", values[field]):
            errors.append(f"GLOBAL字段仍含模板占位符：{field}")

    expected_values = {
        "正式频道名": expected_channel_name,
        "目标语言": expected_language,
        "目标市场": expected_market,
    }
    for field, expected in expected_values.items():
        if expected is not None and values.get(field) != expected:
            errors.append(f"GLOBAL字段与注册表不一致：{field}（期望：{expected}；实际：{values.get(field, '缺失')}）")

    if values.get("GLOBAL权限声明") != PERMISSION:
        errors.append("GLOBAL权限声明不符合固定文本")

    global_without_permission = "\n".join(
        line for line in global_body.splitlines() if not line.startswith("- GLOBAL权限声明：")
    )
    for label, pattern in FORBIDDEN_GLOBAL_PATTERNS.items():
        match = pattern.search(global_without_permission)
        if match:
            errors.append(f"GLOBAL包含禁止内容（{label}）：{match.group(0)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--expected-channel-name")
    parser.add_argument("--expected-language")
    parser.add_argument("--expected-market")
    parser.add_argument("--allow-placeholders", action="store_true", help="仅用于校验模板骨架")
    args = parser.parse_args()
    try:
        text = args.spec.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: 无法读取生成规范：{exc}", file=sys.stderr)
        return 2

    errors = validate_text(
        text,
        expected_channel_name=args.expected_channel_name,
        expected_language=args.expected_language,
        expected_market=args.expected_market,
        allow_placeholders=args.allow_placeholders,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {args.spec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
