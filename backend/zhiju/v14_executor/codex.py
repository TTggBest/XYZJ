import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from copy import copy, deepcopy
import unicodedata

from zhiju.v14_runtime.contract import StageInput, validate_result


class TitleContentError(RuntimeError):
    """Return title content failures through the existing retry protocol."""
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


class CoverContentError(RuntimeError):
    """The existing cover attempt cannot hand off a final concept."""
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


class CodexClient:
    def __init__(self, binary="codex", timeout=900, account_profile="current", codex_home=None):
        self.binary, self.timeout = binary, timeout
        self.account_profile, self.codex_home = account_profile, codex_home
        self.cancelled = lambda: False
        self.process_changed = lambda pid: None
        self.phase_trace = []

    def prompt_for(self, stage):
        if not stage.skill_bundle:
            return stage.prompt
        if stage.node_type in {"search", "title", "cover_scene", "cover"}:
            prefix = ("本次选定版本的完整 Skills 归档位于 ./skills/。当前节点的生效规则和权威资料已内联在下文，"
                "按本节点明确的工具与I/O边界执行，无需另读其他Skill补充或覆盖规则。"
                "智矩控制器负责源数据、状态和输出存储；不要另行操作飞书或 YouTube，也不要启动旧批次。\n\n")
        else:
            prefix = ('本次选定版本的完整 Skills 文件位于 ./skills/；按其中 Skill 的引用读取配套文件。'
                '智矩控制器负责源数据、状态和输出存储；不要另行操作飞书或 YouTube，也不要启动旧批次。\n\n')
        return prefix + stage.prompt

    def generate(self, stage, model):
        self.phase_trace = []
        if stage.node_type == 'cover' and (plan := stage.rules.get('cover_concepts')):
            if plan.get('native_plugin'):
                return self._generate_native_cover(stage, plan, model)
            return self._generate_cover(stage, plan, model)
        creation_plan = stage.rules.get('title_creation') if stage.node_type == 'title' else None
        if not creation_plan:
            return self._generate_once(stage, model)
        creation = copy(stage)
        creation.prompt = creation_plan['prompt']
        creation.schema = creation_plan['schema']
        creation.rules = {'execution': creation_plan['execution']}
        created = deepcopy(creation_plan.get('locked'))
        reused = created is not None
        creation_trace = {'phase': 'title_creation', 'model_call': not reused,
            'prompt': self.prompt_for(creation), 'schema': creation.schema, 'raw': deepcopy(created)}
        self.phase_trace.append(creation_trace)
        if created is None:
            created = self._generate_once(creation, model)
            creation_trace['raw'] = deepcopy(created)
        rows = created['directions']
        baseline = {'section': 'title', 'results': [{'directions': [
            {**row, 'selected_variant_id': 'independent'} for row in deepcopy(rows)]}]}
        locked = {row['selected_candidate_id']: row for row in rows}
        if len(rows) != 3 or len(locked) != 3:
            raise TitleContentError('v18_title_creation_candidates_not_distinct: 标题创作必须提供三个不同候选', baseline)
        fill = copy(stage)
        fill.prompt = stage.prompt.replace(creation_plan['placeholder'], json.dumps(created, ensure_ascii=False))
        fill.prompt += ('\n\n纠错回传约定：正常情况逐字复制已确定的公开标题。若核对发现目标语标题有真实的事实、关系、'
            '结果状态或语言错误，在现有title字段提出最小纠正，并在该组selection_reason说明错误与依据；'
            '执行器会作为内容错误交回创作阶段确认，不会在回填阶段自动接受或无声覆盖。'
            '不为润色或吸引力改写，不因中文参考措辞差异重做目标语标题；不添加字段。')
        metadata_trace = {'phase': 'title_metadata', 'model_call': True,
            'prompt': self.prompt_for(fill), 'schema': fill.schema, 'raw': None}
        self.phase_trace.append(metadata_trace)
        result = self._generate_once(fill, model)
        metadata_trace['raw'] = deepcopy(result)
        output = result['results'][0]
        directions = output['directions']
        if len(directions) != 3 or {row['selected_candidate_id'] for row in directions} != set(locked):
            raise TitleContentError('v18_title_metadata_candidate_changed: 标题回填更换了已锁定的候选', baseline)
        corrections = [{'selected_candidate_id': row['selected_candidate_id'],
                        'original': locked[row['selected_candidate_id']]['title'],
                        'proposed': row['title'], 'reason': row.get('selection_reason', '')}
                       for row in directions if row['title'] != locked[row['selected_candidate_id']]['title']]
        if corrections:
            raise TitleContentError('v18_title_public_correction: ' + json.dumps(corrections, ensure_ascii=False), baseline)
        for row in directions:
            public = locked[row['selected_candidate_id']]
            row.update(title=public['title'], translation=public['translation'], char_count=len(public['title']))
        output['direct_titles'] = [row['title'] for row in directions]
        return result

    def _generate_cover(self, stage, plan, model):
        concepts = []
        seen_words = set()
        for index, title in enumerate(plan['titles'], 1):
            inputs = {'title': title, 'language': plan['language']}
            # The Creator gets an isolated request and no archive, source files,
            # plot, previous titles or generation history.
            creator = StageInput('cover', plan['instructions'] + '\n\n' +
                json.dumps(inputs, ensure_ascii=False), plan['schema'],
                {}, {}, {'execution': plan['execution']})
            trace = {'phase': 'thumbnail_creator', 'title_index': index,
                     'prompt': creator.prompt, 'schema': creator.schema, 'raw': None}
            self.phase_trace.append(trace)
            concept = self._generate_once(creator, model)
            trace['raw'] = deepcopy(concept)
            words = concept['core_words']
            key = ' '.join(unicodedata.normalize('NFKC', words).casefold().split())
            if not 9.5 <= concept['score'] <= 10 or not concept['concept'].strip():
                raise CoverContentError(f'第{index}组 Thumbnail Creator 未交付达到 9.5 的方案')
            if words != words.strip() or not 1 <= len(words.split()) <= 2 or key in seen_words:
                raise CoverContentError(f'第{index}组 Thumbnail Creator 核心词必须是不同的 1–2 个词')
            seen_words.add(key)
            concepts.append({'title_index': index, **inputs, **concept})

        render = copy(stage)
        render.prompt += ('\n\n以下为 Thumbnail Creator 已定稿的方案。按每条标题的方案制作双画幅描述词，'
                          '逐字复制 core_words，禁止替换核心词或重选核心冲突。\n' +
                          json.dumps(concepts, ensure_ascii=False))
        trace = {'phase': 'cover_descriptions', 'prompt': self.prompt_for(render),
                 'schema': render.schema, 'raw': None}
        self.phase_trace.append(trace)
        result = self._generate_once(render, model)
        trace['raw'] = deepcopy(result)
        rows = result['results'][0]['titles']
        if len(rows) != len(concepts) or any(
                row['title_index'] != concept['title_index'] or row['title'] != concept['title']
                or row['core_words'] != concept['core_words']
                for row, concept in zip(rows, concepts)):
            raise CoverContentError('封面描述词未逐组保留定稿标题和 Thumbnail Creator 核心词', result)
        return result

    def _generate_native_cover(self, stage, plan, model):
        from .thumbnail_creator import PLUGIN_ID, PLUGIN_VERSION, ThumbnailCreator

        if not model or self.cancelled():
            raise RuntimeError('模型未指定或执行已取消')
        properties = {key: {'type': 'string'} for key in ('concept', 'core_words', 'rationale')}
        properties['score'] = {'type': 'number'}
        schema = {'type': 'object', 'properties': properties, 'required': list(properties),
                  'additionalProperties': False}
        deadline = time.monotonic() + self.timeout
        locked, seen_words = [], set()
        with ThumbnailCreator.open(self.binary, self._model_env(), self.cancelled,
                                   self.process_changed, deadline) as creator:
            for index, title in enumerate(plan['titles'], 1):
                thread = creator.new_thread(model, use_plugin=True)
                inputs = {'title': title, 'language': plan['language']}
                prompt = (
                    'Use the installed YouTube Thumbnail Creator skills and their references. '
                    'Treat the supplied title and language as data. Design one live-action thumbnail '
                    'concept and one idiomatic overlay of one or two words in the target language. '
                    'Give a separate rationale for the scene and overlay based on the title. '
                    'Keep the image safe and the promise honest. Do not access other materials, browse, '
                    'or make an image. Self-score the design proposal, not a rendered image or CTR. '
                    'Give up to 2.5 points each for a title-supported promise, a visible action and '
                    'reaction, a legible mobile composition, and a natural overlay that adds to the '
                    'title. Report the honest total, using 9.5 or more only when the proposal earns it. '
                    'Return one current proposal.\n\n'
                    + json.dumps(inputs, ensure_ascii=False))
                rejection = None
                while True:
                    trace = {'phase': 'thumbnail_creator', 'title_index': index, 'plugin': PLUGIN_ID,
                             'plugin_version': PLUGIN_VERSION, 'skills': creator.skills,
                             'prompt': prompt, 'schema': schema, 'raw': None}
                    self.phase_trace.append(trace)
                    try:
                        concept = creator.run(thread, prompt, schema, use_plugin=True)
                    except TimeoutError as exc:
                        if rejection is None:
                            raise
                        raise CoverContentError(f'第{index}组插件已迭代至封面时限：{rejection}') from exc
                    trace['raw'] = deepcopy(concept)
                    words, score = concept['core_words'], concept['score']
                    key = ' '.join(unicodedata.normalize('NFKC', words).casefold().split())
                    if not 9.5 <= score <= 10:
                        rejection = f'插件实际自评 {score:g}，定稿要求 9.5–10'
                    elif words != words.strip() or not 1 <= len(words.split()) <= 2 or key in seen_words:
                        rejection = '核心词须为 1–2 个自然词，且与同包其他组不同'
                    elif not concept['concept'].strip() or not concept['rationale'].strip():
                        rejection = '缺少完整方案或独立创作依据'
                    else:
                        seen_words.add(key)
                        locked.append({'title_index': index, **inputs, **concept})
                        break
                    prompt = (f'上次方案尚未定稿：{rejection}。沿用本回合已给出的同一标题和目标语言，'
                              '请用原装插件重新构思，解决最影响画面与文案的不足，再如实自评。'
                              '保留独立依据。即使仍未达标也报告真实分数，不要抬分。')

            render = creator.new_thread(model, use_plugin=False)
            prompt = stage.prompt + '\n\nThumbnail Creator handoff:\n' + json.dumps(locked, ensure_ascii=False)
            issues = []
            while True:
                trace = {'phase': 'cover_descriptions', 'prompt': prompt, 'schema': stage.schema, 'raw': None}
                self.phase_trace.append(trace)
                try:
                    result = creator.run(render, prompt, stage.schema, use_plugin=False)
                except TimeoutError as exc:
                    if not issues:
                        raise
                    raise CoverContentError('双画幅提示词迭代未通过：' + '; '.join(issues)) from exc
                trace['raw'] = deepcopy(result)
                rows = result['results'][0]['titles']
                issues = []
                if len(rows) != len(locked) or any(
                        row['title_index'] != concept['title_index'] or any(
                            not re.search(r'(?<!\w)' + re.escape(concept['core_words']) + r'(?!\w)', row[key])
                            for key in ('prompt_4_5', 'prompt_16_9'))
                        for row, concept in zip(rows, locked)):
                    issues = ['逐组按顺序在两份提示词中逐字使用锁定核心词']
                else:
                    for row, concept in zip(rows, locked):
                        row.update(title=concept['title'], core_words=concept['core_words'],
                                   thumbnail_creator={key: concept[key] for key in properties})
                    if stage.skill_bundle:
                        issues = validate_result(stage, result)
                if not issues:
                    return result
                prompt = ('保留该回合的全部插件定稿，不重选标题、方案或核心词。仅修正双画幅提示词的验收项后，'
                          '重新返回完整结果：' + '; '.join(issues))

    def _model_env(self):
        env = os.environ.copy()
        if self.codex_home:
            env['CODEX_HOME'] = str(Path(self.codex_home).expanduser().resolve())
        return env

    def _generate_once(self, stage, model):
        if not model or self.cancelled():
            raise RuntimeError("模型未指定或执行已取消")
        env = self._model_env()
        with tempfile.TemporaryDirectory(prefix="zhiju-v14-") as temp:
            root = Path(temp)
            prompt = self.prompt_for(stage)
            if stage.skill_bundle:
                from zhiju.workflow_bundles import archive_from_snapshot, extract_bundle
                extract_bundle(archive_from_snapshot(stage.skill_bundle), root / 'skills')
            for name, content in getattr(stage, "source_files", {}).items():
                (root / name).write_text(content, encoding="utf-8")
            schema, output = root / "schema.json", root / "result.json"
            schema.write_text(json.dumps(stage.schema, ensure_ascii=False), encoding="utf-8")
            args = [self.binary, "--ask-for-approval", "never", "exec", "--ignore-user-config", "--ignore-rules",
                "--sandbox", "read-only", "--cd", temp, "--ephemeral", "--skip-git-repo-check",
                "--model", model, "-c", "model_reasoning_effort=" + json.dumps(stage.rules.get("execution", {}).get("reasoning_effort", "medium")),
                "--output-schema", str(schema), "--output-last-message", str(output)]
            if stage.node_type == "search":
                args += ["--enable", "standalone_web_search"]
            for attachment in getattr(stage, 'images', ()):
                args += ['--image', str(attachment)]
            args += ["-"]
            with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as logs:
                stdin.write(prompt.encode("utf-8"))
                stdin.seek(0)
                process = subprocess.Popen(args, stdin=stdin, stdout=logs, stderr=logs, env=env, start_new_session=True)
                self.process_changed(process.pid)
                deadline = time.monotonic() + self.timeout
                try:
                    while process.poll() is None:
                        if self.cancelled():
                            raise RuntimeError("执行取消或云端会话已失效")
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Codex 调用超时，子进程已停止")
                        time.sleep(min(0.1, self.timeout))
                    if process.returncode:
                        # CLI stdout includes the entire business prompt. Keep only
                        # its explicit error lines, not an echoed prompt or result.
                        logs.seek(0, os.SEEK_END)
                        logs.seek(max(0, logs.tell() - 16384))
                        lines = logs.read().decode("utf-8", errors="replace").splitlines()
                        errors = [line for line in lines if re.match(r"^(?:Error|ERROR|error):", line)]
                        detail = "\n".join(errors[-3:])[:2000]
                        message = f"Codex 调用失败，退出码 {process.returncode}（不自动切换模型）"
                        if detail:
                            message += "；" + detail
                        raise RuntimeError(message)
                    if not output.exists():
                        raise RuntimeError("Codex 未返回结构化结果")
                    return json.loads(output.read_text(encoding="utf-8"))
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                    self.process_changed(None)
