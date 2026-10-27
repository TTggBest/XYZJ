from difflib import unified_diff

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from zhiju.auth_context import get_tenant_db
from zhiju.api.v14 import operator, call, ProductionVersion
from zhiju.permissions import require_platform_permission
from zhiju.services import workflow_versions as service
from zhiju.workflow_bundles import inspect_bundle, read_file

router = APIRouter(prefix='/v3/workflow-versions', tags=['workflow-versions'])


@router.get('')
def versions(s: Session = Depends(get_tenant_db), p=Depends(operator)):
    from zhiju.services.v14_runs import get_settings
    setting = get_settings(s)
    return {'versions': service.list_versions(s), 'default_id':
            (setting.payload.get('workflow_version_id') if setting else None) or 'builtin-v14'}


@router.post('', dependencies=[Depends(require_platform_permission)])
def upload(label: str = Form(...), change_summary: str = Form(''), file: UploadFile = File(...),
           s: Session = Depends(get_tenant_db), p=Depends(operator)):
    try:
        data = file.file.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('Skills ZIP 超过 8 MiB')
        return service.describe(call(service.upload, s, label, change_summary, data))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/default')
def set_default(body: ProductionVersion, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return call(service.select_default, s, body.workflow_version_id or 'builtin-v14')


@router.get('/{version_id}/download')
def download(version_id: str, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return Response(call(service.get_archive, s, version_id), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="workflow-skills.zip"'})


@router.get('/{version_id}')
def detail(version_id: str, path: str | None = None, compare_to: str | None = None,
           s: Session = Depends(get_tenant_db), p=Depends(operator)):
    data = call(service.get_archive, s, version_id)
    result = inspect_bundle(data)
    current_files = set(result['files'])
    previous = call(service.get_archive, s, compare_to) if compare_to else None
    previous_files = set(inspect_bundle(previous)['files']) if previous else set()
    if previous:
        result['files'] = sorted(current_files | previous_files)
        result['deleted_files'] = sorted(previous_files - current_files)
        result['added_files'] = sorted(current_files - previous_files)
    if path:
        try:
            if path not in current_files | previous_files:
                raise ValueError('文件不在所选版本中')
            result['content'] = read_file(data, path) if path in current_files else ''
            if previous:
                before = read_file(previous, path) if path in previous_files else ''
                result['diff'] = ''.join(unified_diff(before.splitlines(True), result['content'].splitlines(True),
                    fromfile=compare_to + '/' + path, tofile=version_id + '/' + path))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return result


@router.put('/{version_id}', dependencies=[Depends(require_platform_permission)])
def replace(version_id: str, file: UploadFile = File(...), s: Session = Depends(get_tenant_db), p=Depends(operator)):
    try:
        data = file.file.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('Skills ZIP 超过 8 MiB')
        return service.describe(call(service.replace_draft, s, version_id, data))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/{version_id}/publish', dependencies=[Depends(require_platform_permission)])
def publish(version_id: str, s: Session = Depends(get_tenant_db), p=Depends(operator)):
    return service.describe(call(service.publish, s, version_id))
