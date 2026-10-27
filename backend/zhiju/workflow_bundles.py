"""Transport and execute a trusted administrator's complete Skills archive.

No content prompts or creative validators live in this module. The archive's
entrypoint owns prepare/validate/evidence operations; stdin/stdout are JSON.
"""
import base64
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from zipfile import BadZipFile, ZipFile

BASELINE = Path(__file__).parent / 'workflow_baseline' / 'v14.zip'


def inspect_bundle(data: bytes) -> dict:
    try:
        with ZipFile(BytesIO(data)) as z:
            names = z.namelist()
            if sum(i.file_size for i in z.infolist()) > 32 * 1024 * 1024:
                raise ValueError('Skills 解压内容超过 32 MiB')
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name:
                    raise ValueError('Skills 文件路径必须位于包内')
            manifest = json.loads(z.read('zhiju-workflow.json'))
            if not isinstance(manifest, dict):
                raise ValueError('zhiju-workflow.json 必须是对象')
            entry = manifest['entrypoint']
            if not isinstance(entry, str) or entry not in names or not entry.endswith('.py'):
                raise ValueError('缺少包内 Python 接入入口')
            if not isinstance(manifest.get('skills'), list) or not manifest['skills'] or any(
                    not isinstance(skill, str) or f'{skill}/SKILL.md' not in names for skill in manifest['skills']):
                raise ValueError('缺少完整 Skill 目录或 SKILL.md')
            return {**manifest, 'files': sorted(n for n in names if not n.endswith('/'))}
    except (BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('需要完整 Skills ZIP，根目录须包含 zhiju-workflow.json') from exc


def read_file(data: bytes, path: str) -> str:
    manifest = inspect_bundle(data)
    if path not in manifest['files']:
        raise ValueError('文件不在当前版本中')
    with ZipFile(BytesIO(data)) as z:
        try:
            return z.read(path).decode('utf-8')
        except UnicodeDecodeError:
            return '二进制文件，请下载完整版本查看。'


def extract_bundle(data: bytes, destination: Path) -> dict:
    manifest = inspect_bundle(data)
    with ZipFile(BytesIO(data)) as z:
        z.extractall(destination)
    return manifest


def invoke_bundle(data: bytes, action: str, payload: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix='zhiju-skills-') as temp:
        manifest = extract_bundle(data, Path(temp))
        # No cloud DB/OAuth/Codex secrets are passed to uploaded validators.
        env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'SYSTEMROOT', 'TMPDIR'}}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        try:
            process = subprocess.run([sys.executable, str(Path(temp) / manifest['entrypoint'])],
                input=json.dumps({'action': action, **payload}, ensure_ascii=False),
                capture_output=True, text=True, cwd=temp, env=env, timeout=240 if action == 'evidence' else 60)
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f'Skills {action} 执行超时，请检查所选版本的配套脚本') from exc
        if process.returncode:
            raise ValueError('Skills 执行失败: ' + process.stderr[-3000:])
        return json.loads(process.stdout)


def snapshot(data: bytes, *, version_id: str, label: str, revision: int) -> dict:
    inspect_bundle(data)
    return {'id': version_id, 'label': label, 'revision': revision,
            'archive': base64.b64encode(data).decode('ascii')}


def archive_from_snapshot(bundle: dict) -> bytes:
    return base64.b64decode(bundle['archive'])
