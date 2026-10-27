from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from test_v14_runs import store


def archive(files):
    data = BytesIO()
    with ZipFile(data, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    return data.getvalue()


def test_bundle_runs_uploaded_script_and_preserves_skill_files():
    from zhiju.workflow_bundles import inspect_bundle, invoke_bundle, read_file
    data = archive({
        'zhiju-workflow.json': json.dumps({'entrypoint': 'bridge.py', 'skills': ['demo']}),
        'demo/SKILL.md': '完整工作流说明',
        'demo/rules.txt': 'from-skill-file',
        'bridge.py': "import json,sys\nfrom pathlib import Path\nr=json.load(sys.stdin)\nprint(json.dumps({'value':Path('demo/rules.txt').read_text(),'action':r['action']}))\n",
    })
    assert inspect_bundle(data)['skills'] == ['demo']
    assert read_file(data, 'demo/SKILL.md') == '完整工作流说明'
    assert invoke_bundle(data, 'prepare', {}) == {'value': 'from-skill-file', 'action': 'prepare'}


def test_bundle_rejects_paths_outside_archive():
    from zhiju.workflow_bundles import inspect_bundle
    with pytest.raises(ValueError, match='路径'):
        inspect_bundle(archive({'../oops': 'bad'}))


def test_distributed_baseline_excludes_runtime_caches():
    from zhiju.workflow_bundles import BASELINE, inspect_bundle
    assert not [name for name in inspect_bundle(BASELINE.read_bytes())['files']
                if any(part in {'.pytest_cache', '__pycache__', '.DS_Store'} for part in name.split('/'))]


def test_baseline_uses_original_skill_files_for_generation():
    from zhiju.workflow_bundles import BASELINE, invoke_bundle, read_file
    from test_v14_contract import envelope
    data = BASELINE.read_bytes()
    result = invoke_bundle(data, 'prepare', {'envelope': envelope(), 'node': 'title'})
    assert read_file(data, 'xy-title-v14/SKILL.md') in result['prompt']
    assert read_file(data, 'xy-title-v14/references/model_prompt.md') in result['prompt']
    assert result['schema']['properties']['results']['maxItems'] == 1


def test_baseline_preserves_original_v14_files_and_cast_rule():
    from pathlib import Path
    from zhiju.workflow_bundles import BASELINE, inspect_bundle, invoke_bundle
    from test_v14_contract import envelope
    source = Path('/Volumes/TTggg_mini01_2T/CodexData/.codex/skills')
    if not source.exists():
        pytest.skip('Original operational Skills are only available on the source machine')
    data = BASELINE.read_bytes()
    with ZipFile(BytesIO(data)) as z:
        for name in inspect_bundle(data)['files']:
            if name.split('/')[0].startswith('xy-'):
                assert z.read(name) == (source / name).read_bytes(), name
    e = envelope()
    e['input_snapshot']['drama']['source_language'] = 'en'
    stage = invoke_bundle(data, 'prepare', {'envelope': e, 'node': 'cover'})
    assert 'Chinese' in stage['prompt']
    assert 'Source-language cast requirement:' not in stage['prompt']


def test_bundle_migration_adds_only_version_storage():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from zhiju.models import Base
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'alembic/versions/c72a10b01500_workflow_skill_versions.py'
    spec = importlib.util.spec_from_file_location('skill_versions_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE tenants (id VARCHAR(36) PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE packages (id VARCHAR(36) PRIMARY KEY, status TEXT)')
        connection.exec_driver_sql("INSERT INTO packages VALUES ('existing', 'complete')")
        with Operations.context(MigrationContext.configure(connection, opts={'target_metadata': Base.metadata})):
            migration.upgrade()
        assert set(sa.inspect(connection).get_table_names()) == {'tenants', 'packages', 'workflow_skill_versions'}
        assert connection.exec_driver_sql('SELECT * FROM packages').one() == ('existing', 'complete')
        assert sa.inspect(connection).get_foreign_keys('workflow_skill_versions')[0]['referred_table'] == 'tenants'
        assert sa.inspect(connection).get_check_constraints('workflow_skill_versions')[0]['name'] == 'ck_workflow_skill_versions_workflow_skill_status'
    engine.dispose()


def test_native_cover_validation_assembles_original_cast_without_adapter_error():
    from zhiju.workflow_bundles import BASELINE, invoke_bundle
    from test_v14_contract import envelope
    data = BASELINE.read_bytes()
    stage = invoke_bundle(data, 'prepare', {'envelope': envelope(), 'node': 'cover'})

    # Structurally valid, deliberately uncreative content: business checks may
    # reject it, but native normalization must execute and retain V14's cast.
    def sample(schema):
        if 'enum' in schema:
            return schema['enum'][0]
        if schema['type'] == 'object':
            return {key: sample(schema['properties'][key]) for key in schema['required']}
        if schema['type'] == 'array':
            return [sample(schema['items']) for _ in range(schema.get('minItems', 0))]
        return {'string': 'example', 'integer': 1, 'boolean': False}[schema['type']]

    response = invoke_bundle(data, 'validate', {'stage': stage, 'result': sample(stage['schema'])})
    assert response['issues']
    for row in response['result']['results'][0]['titles']:
        assert 'Chinese actors, Chinese facial features, East Asian appearance' in row['prompt_4_5']


def test_published_bundle_is_immutable_and_revision_can_be_selected():
    from sqlalchemy import create_engine
    from zhiju.models import Base
    from zhiju.database import TenantSession
    from zhiju.services import workflow_versions as svc
    from zhiju.workflow_bundles import BASELINE
    from zhiju.services.identity import ConflictError
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={'tenant_id': 'one'}) as s:
        version = svc.upload(s, 'V15', 'first', BASELINE.read_bytes())
        assert version.status == 'draft'
        with pytest.raises(ConflictError):
            svc.resolve(s, version.id)
        svc.publish(s, version.id)
        assert svc.resolve(s, version.id)['label'] == 'V15'
        with pytest.raises(ConflictError):
            svc.replace_draft(s, version.id, BASELINE.read_bytes())
        second = svc.upload(s, 'V15', 'repair', BASELINE.read_bytes())
        assert second.revision == 2
        assert svc.resolve(s, 'builtin-v14')['label'] == 'V14'
    with TenantSession(engine, info={'tenant_id': 'two'}) as s:
        assert len(svc.list_versions(s)) == 1


def test_production_selects_bundle_at_start_and_freezes_it(store):
    from zhiju.database import TenantSession
    from zhiju.services import v14_runs, workflow_versions as versions
    from zhiju.workflow_bundles import BASELINE
    from test_v14_runs import configure
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        configure(s)
        upgraded = versions.upload(s, 'V15', 'new', BASELINE.read_bytes())
        versions.publish(s, upgraded.id)
        run = v14_runs.create_run(s, 'work-a', workflow_version_id=upgraded.id)
        assert run.input_snapshot['workflow_version']['label'] == 'V15'
        versions.select_default(s, 'builtin-v14')
        assert v14_runs.create_run(s, 'work-a').input_snapshot['workflow_version']['label'] == 'V15'
        assert v14_runs.envelope(s, run)['rules_snapshot']['skill_bundle']['archive']


def test_skill_prompt_and_validator_changes_take_effect_without_app_changes():
    from zhiju.workflow_bundles import BASELINE, invoke_bundle
    from test_v14_contract import envelope
    original = BASELINE.read_bytes()
    with ZipFile(BytesIO(original)) as z:
        files = {name: z.read(name) for name in z.namelist()}
    files['xy-title-v14/references/model_prompt.md'] += b'\nBUNDLE-ONLY-REVISION\n'
    files['zhiju/bridge.py'] = files['zhiju/bridge.py'].replace(
        b"result.get('text_complete') is True", b"result.get('text_complete') is False")
    changed = archive(files)
    assert 'BUNDLE-ONLY-REVISION' in invoke_bundle(changed, 'prepare', {'envelope': envelope(), 'node': 'title'})['prompt']
    stage = invoke_bundle(original, 'prepare', {'envelope': envelope(), 'node': 'merge'})
    assert invoke_bundle(original, 'validate', {'stage': stage, 'result': {'text_complete': False}})['issues']
    assert not invoke_bundle(changed, 'validate', {'stage': stage, 'result': {'text_complete': False}})['issues']


def test_bundle_timeout_is_a_readable_workflow_error(monkeypatch):
    import subprocess
    from zhiju import workflow_bundles as bundles
    def expired(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)
    monkeypatch.setattr(bundles.subprocess, 'run', expired)
    with pytest.raises(ValueError, match='Skills.*prepare.*超时'):
        bundles.invoke_bundle(bundles.BASELINE.read_bytes(), 'prepare', {})
