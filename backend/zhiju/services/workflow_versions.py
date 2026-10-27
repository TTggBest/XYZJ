from sqlalchemy import select, func

from zhiju.models.v14 import WorkflowSkillVersion, V14Setting
from zhiju.services.identity import ConflictError
from zhiju.tenant_repository import require_tenant_entity
from zhiju.workflow_bundles import BASELINE, inspect_bundle, snapshot

BUILTIN = {'id': 'builtin-v14', 'label': 'V14', 'revision': 1,
           'status': 'published', 'change_summary': '完整 V14 Skills；附智矩数据接入与本机检索工具路径适配，创意规则不变。'}


def describe(row):
    return {k: getattr(row, k) for k in ('id', 'label', 'revision', 'status', 'change_summary')}


def list_versions(session):
    rows = session.scalars(select(WorkflowSkillVersion).where(
        WorkflowSkillVersion.tenant_id == session.info['tenant_id']).order_by(WorkflowSkillVersion.created_at.desc()))
    return [BUILTIN, *(describe(r) for r in rows)]


def get_archive(session, version_id):
    if version_id == BUILTIN['id']:
        return BASELINE.read_bytes()
    return require_tenant_entity(session, WorkflowSkillVersion, version_id).archive


def resolve(session, version_id):
    if version_id == BUILTIN['id']:
        info, data = BUILTIN, BASELINE.read_bytes()
    else:
        row = require_tenant_entity(session, WorkflowSkillVersion, version_id)
        if row.status != 'published':
            raise ConflictError('只能选择已发布的 Skills 版本')
        info, data = describe(row), row.archive
    return snapshot(data, version_id=info['id'], label=info['label'], revision=info['revision'])


def upload(session, label, change_summary, data):
    inspect_bundle(data)
    label = label.strip()
    if not label or len(label) > 80:
        raise ValueError('版本名称不能为空且不能超过 80 字符')
    # Same tenant lock as starting/accepting a production run.
    session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info['tenant_id']).with_for_update())
    revision = session.scalar(select(func.max(WorkflowSkillVersion.revision)).where(
        WorkflowSkillVersion.tenant_id == session.info['tenant_id'], WorkflowSkillVersion.label == label)) or 0
    if label == 'V14':
        revision = max(1, revision)
    row = WorkflowSkillVersion(tenant_id=session.info['tenant_id'], label=label,
        revision=revision + 1, change_summary=change_summary, archive=data, status='draft')
    session.add(row)
    session.commit()
    return row


def replace_draft(session, version_id, data):
    row = require_tenant_entity(session, WorkflowSkillVersion, version_id, lock=True)
    if row.status != 'draft':
        raise ConflictError('已发布版本不能覆盖，请上传新的修订版')
    inspect_bundle(data)
    row.archive = data
    session.commit()
    return row


def publish(session, version_id):
    row = require_tenant_entity(session, WorkflowSkillVersion, version_id, lock=True)
    inspect_bundle(row.archive)
    row.status = 'published'
    session.commit()
    return row


def select_default(session, version_id):
    resolve(session, version_id)
    setting = session.scalar(select(V14Setting).where(V14Setting.tenant_id == session.info['tenant_id']).with_for_update())
    if not setting:
        raise ConflictError('请先配置执行主机与频道材料')
    setting.payload = {**setting.payload, 'workflow_version_id': version_id}
    session.commit()
    return {'workflow_version_id': version_id}
