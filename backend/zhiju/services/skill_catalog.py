"""One catalog; production versions retain their existing IDs and storage."""
from difflib import unified_diff
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile, BadZipFile
from sqlalchemy import select, func
from zhiju.models import SkillCategory, SkillBundleVersion
from zhiju.models.v14 import V14Setting
from zhiju.services import workflow_versions
from zhiju.services.identity import ConflictError
from zhiju.tenant_repository import require_tenant_entity
from zhiju.workflow_bundles import inspect_bundle, read_file

ANALYSIS = 'channel-analysis'
PRODUCTION = 'package-production'
INITIALIZATION = 'channel-initialization'
SCHEDULING = 'channel-scheduling'
SCHEDULING_VERSION = 'builtin-channel-scheduling-v1'
SCHEDULING_V2_VERSION = 'builtin-channel-scheduling-v2'
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


def initialization_modules(s):
    from zhiju.services.settings import list_channel_initialization_rules
    return [m for m in list_channel_initialization_rules(s)
            if m['module_key'] not in {'initial_analysis', 'operating_reference'}]


def sync_initialization(s):
    from zhiju.schemas.skill import SkillCreate
    from zhiju.services.skill import create_skill
    for module in initialization_modules(s):
        if not module['skill_id']:
            create_skill(s, SkillCreate(code=module['skill_code'],name=module['module_name'],
                purpose=module['output_description'],category='channel-initialization'))
    return initialization_modules(s)


def category(s, key):
    if key == SCHEDULING:
        return {'id':key,'name':'频道排期','description':'依据频道生效资料和真实剧情选剧，生成预览后保存', 'execution':'channel_scheduling'}
    if key == INITIALIZATION:
        return {'id':key, 'name':'频道初始化', 'description':'频道基础资料与运营配置，共 9 项规则模块',
                'execution':'channel_initialization', 'modules':initialization_modules(s)}
    if key in {ANALYSIS, PRODUCTION}:
        return {'id':key, 'name':'频道分析' if key == ANALYSIS else '运营包生产',
                'description':'频道画像、运营诊断与生成规范' if key == ANALYSIS else '搜索、标题、封面、说明、社群与合成',
                'execution':'channel_analysis' if key == ANALYSIS else 'package_production'}
    row = require_tenant_entity(s, SkillCategory, key)
    return {'id':row.id, 'name':row.name, 'description':row.description, 'execution':None}


def default_id(s, key):
    if key == SCHEDULING:
        setting=s.scalar(select(V14Setting))
        return (setting.payload.get('scheduling_skill_version_id') if setting else None) or SCHEDULING_VERSION
    if key == INITIALIZATION:return None
    if key in {PRODUCTION, ANALYSIS}:
        setting = s.scalar(select(V14Setting))
        payload = setting.payload if setting else {}
        return (payload.get('workflow_version_id') or 'builtin-v14') if key == PRODUCTION else (payload.get('analysis_skill_version_id') or ANALYSIS_VERSION)
    return require_tenant_entity(s, SkillCategory, key).default_version_id


def version_read(row):
    return {k:getattr(row,k) for k in ('id','label','revision','status','change_summary')}


def versions(s, key):
    category(s,key)
    if key == INITIALIZATION:return []
    if key == PRODUCTION:
        return workflow_versions.list_versions(s)
    rows = [version_read(r) for r in s.scalars(select(SkillBundleVersion).where(
        SkillBundleVersion.category_id == key).order_by(SkillBundleVersion.created_at.desc(), SkillBundleVersion.id))]
    if key == ANALYSIS:
        rows.append({'id':ANALYSIS_VERSION, 'label':'xy-yt-report-v2', 'revision':1, 'status':'published',
                     'change_summary':'完整原始 Skill、引用规则与校验脚本。分析执行链路尚待原流程一致性验收。'})
    if key == SCHEDULING:
        rows.append({'id':SCHEDULING_V2_VERSION,'label':'channel-scheduling-v2','revision':1,'status':'published',
                     'change_summary':'V2：完整库存、细分观看需求、逐档序列比较、强主题缺口与发布反馈；v1保留'})
        rows.append({'id':SCHEDULING_VERSION,'label':'channel-scheduling','revision':1,'status':'published',
                     'change_summary':'智矩通用排期：最终合成与逐语言库存、真实剧情选剧、预览与确认保存'})
    return rows


def catalog(s):
    keys = [ANALYSIS, PRODUCTION, SCHEDULING, INITIALIZATION, *s.scalars(select(SkillCategory.id).order_by(SkillCategory.created_at, SkillCategory.id))]
    return [{**category(s,k), 'versions':versions(s,k), 'default_id':default_id(s,k)} for k in keys]


def create_category(s, name, description):
    name=name.strip()
    if not name or len(name)>80:raise ValueError('分类名称须为 1～80 字')
    if name in {'频道分析','运营包生产','频道初始化','频道排期'} or s.scalar(select(SkillCategory.id).where(SkillCategory.name==name)):
        raise ConflictError('分类名称已存在')
    row=SkillCategory(name=name,description=description.strip())
    s.add(row);s.commit();s.refresh(row)
    return category(s,row.id)


def archive(s,key,version_id):
    category(s,key)
    if key==INITIALIZATION:raise ConflictError('请在对应初始化模块内管理规则版本')
    if key==PRODUCTION:return workflow_versions.get_archive(s,version_id)
    if key==ANALYSIS and version_id==ANALYSIS_VERSION:return BUNDLE.read_bytes()
    if key==SCHEDULING and version_id in {SCHEDULING_VERSION, SCHEDULING_V2_VERSION}:
        from zipfile import ZIP_DEFLATED
        buffer=BytesIO()
        root=Path(__file__).resolve().parents[1]/('scheduling_v2_rules' if version_id == SCHEDULING_V2_VERSION else 'scheduling_rules')
        with ZipFile(buffer,'w',ZIP_DEFLATED) as z:
            for path in root.rglob('*'):
                if version_id == SCHEDULING_V2_VERSION and '__pycache__' in path.parts:
                    continue
                if path.is_file():z.writestr(path.relative_to(root).as_posix(),path.read_bytes())
        return buffer.getvalue()
    row=require_tenant_entity(s,SkillBundleVersion,version_id)
    if row.category_id!=key:raise ConflictError('版本不属于此分类')
    return row.archive


def review_production_skills(session, version_id, skill=None, compare_to=None):
    data = archive(session, PRODUCTION, version_id)
    skills = inspect_bundle(data)['skills']
    selected = skill if skill is not None else skills[0]
    if selected not in skills:
        raise ValueError('Skill 不在所选运营包版本中')
    content = read_file(data, f'{selected}/SKILL.md')
    result = {'skills': skills, 'skill': selected, 'content': content,
              'compared_skill': None, 'diff': None, 'comparison_only': []}
    if not compare_to:
        return result

    previous = archive(session, PRODUCTION, compare_to)
    previous_skills = inspect_bundle(previous)['skills']

    def skill_key(name):
        return re.sub(r'-v[0-9]+$', '', name)

    current_keys = {skill_key(name) for name in skills}
    result['comparison_only'] = [name for name in previous_skills if skill_key(name) not in current_keys]
    compared = selected if selected in previous_skills else next(
        (name for name in previous_skills if skill_key(name) == skill_key(selected)), None)
    if compared is not None:
        before = read_file(previous, f'{compared}/SKILL.md')
        result['compared_skill'] = compared
        result['diff'] = '\n'.join(unified_diff(before.splitlines(), content.splitlines(),
                                               fromfile=compared, tofile=selected, lineterm=''))
    return result


def upload(s,key,label,summary,data):
    category(s,key)
    if key==INITIALIZATION:raise ConflictError('请在对应初始化模块内添加规则版本')
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
    if key==SCHEDULING and label=='channel-scheduling':revision=max(1,revision)
    if key==SCHEDULING and label=='channel-scheduling-v2':revision=max(1,revision)
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
    if version_id not in {ANALYSIS_VERSION,SCHEDULING_VERSION,SCHEDULING_V2_VERSION}:
        row=require_tenant_entity(s,SkillBundleVersion,version_id)
        if row.status!='published':raise ConflictError('只能指定已发布版本')
    if key in {ANALYSIS,SCHEDULING}:
        setting=s.scalar(select(V14Setting).with_for_update())
        if not setting:raise ConflictError('请先配置执行主机')
        setting.payload={**setting.payload,('analysis_skill_version_id' if key==ANALYSIS else 'scheduling_skill_version_id'):version_id}
    else:
        require_tenant_entity(s,SkillCategory,key,lock=True).default_version_id=version_id
    s.commit();return {'default_id':version_id}


def analysis_snapshot(s):
    key=default_id(s,ANALYSIS)
    content=files(archive(s,ANALYSIS,key))
    version=next(v for v in versions(s,ANALYSIS) if v['id']==key)
    if version['status']!='published':raise ConflictError('分析 Skill 尚未发布')
    return {**version,'files':content}


def scheduling_snapshot(s):
    key=default_id(s,SCHEDULING)
    version=next(v for v in versions(s,SCHEDULING) if v['id']==key)
    if version['status']!='published':raise ConflictError('排期 Skill 尚未发布')
    return {**version,'files':files(archive(s,SCHEDULING,key))}
