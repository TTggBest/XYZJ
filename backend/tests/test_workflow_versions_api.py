from dataclasses import replace

from test_v14_api import client, PRINCIPAL
from test_v14_runs import store
from zhiju import auth_context
from zhiju.workflow_bundles import BASELINE


def test_admin_upload_review_publish_and_choose_previous_version(client):
    data = BASELINE.read_bytes()
    assert client.post('/api/v3/workflow-versions', data={'label': 'V15'},
                       files={'file': ('skills.zip', data)}).status_code == 403
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, platform_role='super_admin')
    response = client.post('/api/v3/workflow-versions', data={'label': 'V15', 'change_summary': 'new'},
                           files={'file': ('skills.zip', data)})
    assert response.status_code == 200, response.text
    version_id = response.json()['id']
    assert client.get(f'/api/v3/workflow-versions/{version_id}/download').content == data
    detail = client.get(f'/api/v3/workflow-versions/{version_id}', params={'path': 'xy-cover-v14/SKILL.md', 'compare_to': 'builtin-v14'}).json()
    assert '# XY Cover' in detail['content']
    assert detail['diff'] == ''
    assert client.post(f'/api/v3/workflow-versions/{version_id}/publish').status_code == 200
    assert client.get('/api/v3/workflow-versions').json()['default_id'] == 'builtin-v14'
    assert client.post('/api/v3/workflow-versions/default', json={'workflow_version_id': version_id}).status_code == 200
    assert client.put(f'/api/v3/workflow-versions/{version_id}', files={'file': ('skills.zip', data)}).status_code == 409
    assert client.post('/api/v3/workflow-versions/default', json={'workflow_version_id': 'builtin-v14'}).status_code == 200
    response = client.post('/api/v3/work-orders/work-a/v14-runs', json={'workflow_version_id': version_id})
    assert response.json()['workflow_version']['label'] == 'V15'


def test_old_executor_cannot_claim_bundle_run_or_damage_queued_state(client):
    run = client.post('/api/v3/work-orders/work-a/v14-runs').json()
    response = client.post('/api/v3/v14/claims', json={'host_id': 'device-a'})
    assert response.status_code == 409
    assert '更新' in response.json()['detail']
    assert client.get('/api/v3/work-orders/work-a/v14-runs/current').json()['status'] == 'queued'
    assert client.post('/api/v3/v14/claims', json={'host_id': 'device-a', 'executor_protocol': 2}).json()['run_id'] == run['run_id']


def test_file_review_includes_deleted_files(client):
    from io import BytesIO
    from zipfile import ZipFile
    from test_workflow_bundles import archive
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, platform_role='super_admin')
    with ZipFile(BytesIO(BASELINE.read_bytes())) as z:
        files = {name: z.read(name) for name in z.namelist()}
    deleted = 'xy-cover-v14/references/model_prompt.md'
    del files[deleted]
    response = client.post('/api/v3/workflow-versions', data={'label': 'V15'},
                           files={'file': ('skills.zip', archive(files))})
    assert response.status_code == 200
    detail = client.get('/api/v3/workflow-versions/' + response.json()['id'],
                        params={'path': deleted, 'compare_to': 'builtin-v14'}).json()
    assert deleted in detail['files'] and deleted in detail['deleted_files']
    assert detail['content'] == ''
    assert '-#' in detail['diff']
