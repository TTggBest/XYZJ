"""One catalog; production versions retain their existing IDs and storage."""
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, BadZipFile
from sqlalchemy import select, func
from zhiju.models import SkillCategory, SkillBundleVersion
from zhiju.models.v14 import V14Setting
from zhiju.services import workflow_versions
from zhiju.services.identity import ConflictError
from zhiju.tenant_repository import require_tenant_entity

ANALYSIS = 'channel-analysis'
PRODUCTION = 'package-production'
ANALYSIS_VERSION = 'builtin-xy-yt-report-v2'
BUNDLE = Path(__file__).resolve().parents[1] / 'skill_catalog_bundles/xy-yt-report-v2.zip'


def files(data):
    try:
        with ZipFile(BytesIO(data)) as z:
            entries = [i for i in z.infolist() if not i.is_dir()]
            if not entries or sum(i.file_size for i in entries) > 32*1024*1024:
                raise ValueError('Skill 解压后不能为空或超过 32 MiB')
            names = [i.filename for i in entries]
            if len(set(names)) != len(names):
                raise ValueError('ZIP 包含重复文件路径')
            if any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts for n in names):
                raise ValueError('ZIP 文件路径无效')
            result = {}
            for item in entries:
                # References, scripts and resources remain together in the original archive.
                try:
                    result[item.filename] = z.read(item).decode('utf-8')
                except UnicodeDecodeError:
                    result[item.filename] = None
            if 'SKILL.md' not in result or not result['SKILL.md']:
                raise ValueError('ZIP 根目录必须包含 UTF-8 SKILL.md')
            return result
    except BadZipFile as exc:
        raise ValueError('无法读取 Skills ZIP') from exc


def category(s, key):
    if key in {ANALYSIS, PRODUCTION}:
        return {'id':key, 'name':'频道分析' if key == ANALYSIS else '运营包生产',
                'description':'频道画像、运营诊断与生成规范' if key == ANALYSIS else '搜索、标题、封面、说明、社群与合成',
                'execution':'channel_analysis' if key == ANALYSIS else 'package_production'}
    row = require_tenant_entity(s, SkillCategory, key)
    return {'id':row.id, 'name':row.name, 'description':row.description, 'execution':None}


def default_id(s, key):
    if key in {PRODUCTION, ANALYSIS}:
        setting = s.scalar(select(V14Setting))
        payload = setting.payload if setting else {}
        return (payload.get('workflow_version_id') or 'builtin-v14') if key == PRODUCTION else (payload.get('analysis_skill_version_id') or ANALYSIS_VERSION)
    return require_tenant_entity(s, SkillCategory, key).default_version_id


def version_read(row):
    return {k:getattr(row,k) for k in ('id','label','revision','status','change_summary')}


def versions(s, key):
    category(s,key)
    if key == PRODUCTION:
        return workflow_versions.list_versions(s)
    rows = [version_read(r) for r in s.scalars(select(SkillBundleVersion).where(
        SkillBundleVersion.category_id == key).order_by(SkillBundleVersion.created_at.desc(), SkillBundleVersion.id))]
    if key == ANALYSIS:
        rows.append({'id':ANALYSIS_VERSION, 'label':'xy-yt-report-v2', 'revision':1, 'status':'published',
                     'change_summary':'完整原始 Skill、引用规则与校验脚本。分析执行链路尚待原流程一致性验收。'})
    return rows


def catalog(s):
    keys = [ANALYSIS, PRODUCTION, *s.scalars(select(SkillCategory.id).order_by(SkillCategory.created_at, SkillCategory.id))]
    return [{**category(s,k), 'versions':versions(s,k), 'default_id':default_id(s,k)} for k in keys]


def create_category(s, name, description):
    name=name.strip()
    if not name or len(name)>80:raise ValueError('分类名称须为 1～80 字')
    if name in {'频道分析','运营包生产'} or s.scalar(select(SkillCategory.id).where(SkillCategory.name==name)):
        raise ConflictError('分类名称已存在')
    row=SkillCategory(name=name,description=description.strip())
    s.add(row);s.commit();s.refresh(row)
    return category(s,row.id)


def archive(s,key,version_id):
    category(s,key)
    if key==PRODUCTION:return workflow_versions.get_archive(s,version_id)
    if key==ANALYSIS and version_id==ANALYSIS_VERSION:return BUNDLE.read_bytes()
    row=require_tenant_entity(s,SkillBundleVersion,version_id)
    if row.category_id!=key:raise ConflictError('版本不属于此分类')
    return row.archive


def upload(s,key,label,summary,data):
    category(s,key)
    if key==PRODUCTION:return workflow_versions.describe(workflow_versions.upload(s,label,summary,data))
    content=files(data)
    if key==ANALYSIS:
        required={'SKILL.md', *(f'references/{name}' for name in ('authorization.md','asset-contract.md','analysis-rules.md','output-contract.md','generation-spec-contract.md')), 'scripts/validate_generation_spec.py'}
        if required-content.keys():raise ValueError('频道分析 Skill 缺少必要文件：'+', '.join(sorted(required-content.keys())))
    label=label.strip()
    if not label or len(label)>80:raise ValueError('版本名称须为 1～80 字')
    # Serialize revisions with the same tenant setting used by production defaults.
    s.scalar(select(V14Setting).with_for_update())
    revision=s.scalar(select(func.max(SkillBundleVersion.revision)).where(SkillBundleVersion.category_id==key,SkillBundleVersion.label==label)) or 0
    if key==ANALYSIS and label=='xy-yt-report-v2':revision=max(1,revision)
    row=SkillBundleVersion(category_id=key,label=label,revision=revision+1,status='draft',change_summary=summary,archive=data)
    s.add(row);s.commit();s.refresh(row)
    return version_read(row)


def publish(s,key,version_id):
    if key==PRODUCTION:return workflow_versions.describe(workflow_versions.publish(s,version_id))
    archive(s,key,version_id)
    row=require_tenant_entity(s,SkillBundleVersion,version_id)
    row.status='published';s.commit();return version_read(row)


def select_default(s,key,version_id):
    category(s,key)
    if key==PRODUCTION:return workflow_versions.select_default(s,version_id)
    archive(s,key,version_id)
    if version_id!=ANALYSIS_VERSION:
        row=require_tenant_entity(s,SkillBundleVersion,version_id)
        if row.status!='published':raise ConflictError('只能指定已发布版本')
    if key==ANALYSIS:
        setting=s.scalar(select(V14Setting).with_for_update())
        if not setting:raise ConflictError('请先配置执行主机')
        setting.payload={**setting.payload,'analysis_skill_version_id':version_id}
    else:
        require_tenant_entity(s,SkillCategory,key,lock=True).default_version_id=version_id
    s.commit();return {'default_id':version_id}


def analysis_snapshot(s):
    key=default_id(s,ANALYSIS)
    content=files(archive(s,ANALYSIS,key))
    version=next(v for v in versions(s,ANALYSIS) if v['id']==key)
    if version['status']!='published':raise ConflictError('分析 Skill 尚未发布')
    return {**version,'files':content}
