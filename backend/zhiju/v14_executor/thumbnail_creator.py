"""Native Codex App Server adapter for the installed Thumbnail Creator plugin."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time


PLUGIN_ID = 'youtube-thumbnail-creator@openai-curated-remote'
PLUGIN_VERSION = '1.0.1'
SKILL_NAMES = tuple(f'youtube-thumbnail-creator:{name}' for name in ('concepts', 'text', 'critique'))
PERMISSIONS = 'zhiju-cover'


class ThumbnailCreator:
    def __init__(self, process, root, cancelled, deadline):
        self.process, self.root, self.cancelled, self.deadline = process, root, cancelled, deadline
        self.sequence = 0
        self.pending = b''
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)

    @classmethod
    @contextmanager
    def open(cls, binary, env, cancelled, process_changed, deadline):
        # Keep installed plugin discovery and the same account. No other apps,
        # memory, hooks, MCP or web search are needed for this isolated job.
        with tempfile.TemporaryDirectory(prefix='zhiju-thumbnail-') as root:
            args = [binary, 'app-server', '--listen', 'stdio://',
                    '--disable', 'apps', '--disable', 'memories', '--disable', 'hooks',
                    '-c', 'mcp_servers={}', '-c', 'web_search="disabled"', '-c', 'allow_login_shell=false']
            with subprocess.Popen(args, cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, start_new_session=True, bufsize=0) as process:
                server = cls(process, str(Path(root).resolve()), cancelled, deadline)
                process_changed(process.pid)
                try:
                    server._initialize()
                    yield server
                finally:
                    server.selector.close()
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                    process_changed(None)

    def _send(self, value):
        self.process.stdin.write((json.dumps(value, ensure_ascii=False) + '\n').encode())

    def _next(self):
        while True:
            if self.cancelled():
                raise RuntimeError('封面执行已取消或云端会话已失效')
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('封面调用达到本次执行时限')
            if b'\n' in self.pending:
                line, _, self.pending = self.pending.partition(b'\n')
                return json.loads(line)
            if self.selector.select(min(remaining, 0.2)):
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError('Codex App Server 提前退出')
                self.pending += chunk

    def _events(self):
        while True:
            event = self._next()
            if 'id' in event and 'method' in event:
                self._send({'id': event['id'], 'error': {'code': -32601, 'message': 'Request unavailable in cover execution'}})
            else:
                yield event

    def _request(self, method, params):
        self.sequence += 1
        self._send({'id': self.sequence, 'method': method, 'params': params})
        for event in self._events():
            if event.get('id') != self.sequence:
                continue
            if 'error' in event:
                raise RuntimeError(f'Codex App Server {method} 请求失败：{event["error"]["message"][:500]}')
            return event['result']

    def _initialize(self):
        self._request('initialize', {'clientInfo': {'name': 'zhiju-thumbnail-creator', 'version': '1'},
                                     'capabilities': {'experimentalApi': True}})
        self._send({'method': 'initialized'})
        plugins = self._request('plugin/list', {'cwds': [self.root]})
        plugin = next((row for market in plugins['marketplaces'] for row in market['plugins']
                       if row['id'] == PLUGIN_ID and row['installed'] and row['enabled']), None)
        if not plugin or (plugin.get('localVersion') or plugin.get('version')) != PLUGIN_VERSION:
            raise RuntimeError(f'当前 Codex 账号需启用 YouTube Thumbnail Creator {PLUGIN_VERSION}')
        listing = self._request('skills/list', {'cwds': [self.root], 'forceReload': True})
        found = {skill['name']: Path(skill['path']).resolve() for group in listing['data']
                 for skill in group['skills'] if skill['enabled'] and skill['name'] in SKILL_NAMES}
        if set(found) != set(SKILL_NAMES):
            raise RuntimeError('Codex 未发现已启用的原装 Thumbnail Creator 技能')
        roots = {path.parents[2] for path in found.values()}
        self.plugin_root = next(iter(roots))
        if (len(roots) != 1 or self.plugin_root.name != PLUGIN_VERSION or self.plugin_root.parent.name != plugin['name']
                or any(path != self.plugin_root / 'skills' / name.split(':')[1] / 'SKILL.md'
                       or not path.is_file() for name, path in found.items())):
            raise RuntimeError('Thumbnail Creator 技能路径与已安装插件不一致')
        self.skills = [{'type': 'skill', 'name': name, 'path': str(found[name])} for name in SKILL_NAMES]

    def new_thread(self, model, *, use_plugin):
        readable = {':minimal': 'read', self.root: 'read'}
        if use_plugin:
            readable[str(self.plugin_root)] = 'read'
        result = self._request('thread/start', {
            'cwd': self.root, 'ephemeral': True, 'model': model, 'allowProviderModelFallback': False,
            'approvalPolicy': 'never', 'multiAgentMode': 'none', 'permissions': PERMISSIONS,
            'config': {f'permissions.{PERMISSIONS}.filesystem': readable,
                       f'permissions.{PERMISSIONS}.network.enabled': False},
        })
        if (result.get('activePermissionProfile') or {}).get('id') != PERMISSIONS:
            raise RuntimeError('封面只读隔离权限未生效')
        return result['thread']['id']

    def run(self, thread, prompt, schema, *, use_plugin):
        turn = self._request('turn/start', {
            'threadId': thread, 'effort': 'medium', 'outputSchema': schema,
            'input': [{'type': 'text', 'text': prompt}, *(self.skills if use_plugin else [])],
        })['turn']['id']
        answer = None
        for event in self._events():
            params = event.get('params', {})
            if params.get('threadId') != thread:
                continue
            if event.get('method') == 'item/completed' and params.get('turnId') == turn:
                item = params['item']
                if item['type'] == 'agentMessage' and item.get('phase') != 'commentary':
                    answer = item['text']
            if event.get('method') == 'turn/completed' and params['turn']['id'] == turn:
                if params['turn']['status'] != 'completed' or answer is None:
                    raise RuntimeError('Codex App Server 封面回合未返回结构化结果')
                return json.loads(answer)
