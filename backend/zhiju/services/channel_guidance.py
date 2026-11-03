"""Resolve the applied channel documents; generation does not change this selection."""
from copy import deepcopy
from sqlalchemy import select
from zhiju.models import ChannelDnaVersion, ChannelAnalysisReport, ChannelAnalysisRun, ChannelProfile, ChannelSchedulePlan
from zhiju.models.v14 import V14Setting
from zhiju.tenant_repository import require_tenant_entity
from zhiju.services.identity import ConflictError


def resolve(session, channel_id, dna_id=None):
    dna = require_tenant_entity(session, ChannelDnaVersion, dna_id) if dna_id else session.scalar(
        select(ChannelDnaVersion).where(ChannelDnaVersion.channel_id==channel_id,
        ChannelDnaVersion.status=='active').order_by(ChannelDnaVersion.version_number.desc()).limit(1))
    setting=session.scalar(select(V14Setting))
    material=(setting.payload.get('channel_inputs',{}).get(channel_id,{}) if setting else {})
    if dna:
        if dna.channel_id != channel_id:raise ConflictError('频道资料版本不属于当前频道')
        plan=session.scalar(select(ChannelSchedulePlan).where(ChannelSchedulePlan.dna_id==dna.id,
            ChannelSchedulePlan.status=='applied'))
        if plan:
            return {**deepcopy(plan.input_snapshot['guidance']),'dna_id':dna.id,'source':'schedule_plan'}
        run=session.scalar(select(ChannelAnalysisRun).where(ChannelAnalysisRun.dna_id==dna.id))
        report=require_tenant_entity(session,ChannelAnalysisReport,dna.analysis_report_id) if dna.analysis_report_id else None
        spec=dna.reference_summary or ''
        source='analysis' if run else 'dna_spec'
        if not run:
            from zhiju.v14_runtime.channel import channel_generation_spec_sections
            try:channel_generation_spec_sections(spec)
            except ValueError:
                source='legacy_reference'
                spec=material.get('generation_spec','')
        return {'source':source,'operating_reference':dna.reference_summary or '', 'dna_id':dna.id,'run_id':run.id if run else None,'report_id':dna.analysis_report_id,
                'mode':report.report_type if report else 'initial',
                'profile':(run.result or {}).get('profile') if run else dna.audience_summary or (report.summary if report else ''),
                'diagnosis':(run.result or {}).get('diagnosis') if run else ((report.recommendations or report.summary) if report else ''),
                'generation_spec':spec,
                'positioning':dna.primary_genre,
                'normalized_snapshot':deepcopy((run.result or {}).get('normalized_snapshot')) if run else None}
    profile=session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id==channel_id))
    positioning=(profile.positioning if profile else '') or ''
    spec=material.get('generation_spec','')
    if not positioning and not spec:
        raise ConflictError('频道缺少冷启动定位或已生效分析资料，请先建立定位或应用分析结果')
    return {'source':'initial','dna_id':None,'run_id':None,'report_id':None,'mode':'initial','profile':positioning,
            'diagnosis':'冷启动定位，未经数据验证','generation_spec':spec,'positioning':positioning,
            'normalized_snapshot':None}
