"""Copy the original complete V14 Skills into the distributable baseline.

Never edits source Skills; no production, network, Feishu or model calls.
"""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build(skills_root, workspace, output):
    names = ['xy-' + s + '-v14' for s in ('workflow', 'generate-tasks', 'batch', 'find', 'title',
        'cover', 'place', 'post', 'pack', 'finalize', 'sort', 'logo')]
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        for name in names:
            source = skills_root / name
            if not (source / 'SKILL.md').is_file():
                raise ValueError('Missing Skill: ' + name)
            for p in sorted(source.rglob('*')):
                if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
                    z.write(p, name + '/' + p.relative_to(source).as_posix())
        adapter = Path(__file__).resolve().parents[1] / 'backend/zhiju/workflow_baseline/bridge.py'
        z.write(adapter, 'zhiju/bridge.py')
        # Original batch imports this module; its Feishu functions are never invoked.
        z.write(workspace / 'tools/feishu_sync/feishu_sheet_sync.py', 'tools/feishu_sheet_sync.py')
        lock = workspace / '运营/工作流实验室/V14/公用/XY生产锁定规范_V14.md'
        z.write(lock, '运营/工作流实验室/V14/公用/XY生产锁定规范_V14.md')
        z.writestr('zhiju-workflow.json', json.dumps({'format': 1, 'label': 'V14', 'entrypoint': 'zhiju/bridge.py',
            'skills': names, 'nodes': ['search', 'title', 'cover', 'description', 'community', 'merge']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.skills_root, args.workspace, args.output)
