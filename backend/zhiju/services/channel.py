from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import (
    Channel,
    ChannelAnalysisEvidence,
    ChannelAnalysisKeywordScore,
    ChannelAnalysisReport,
    ChannelAnalysisTopicScore,
    ChannelAudienceProfile,
    ChannelBrandingAsset,
    ChannelDramaType,
    ChannelDnaSignal,
    ChannelDnaVersion,
    ChannelKeyword,
    ChannelInitializationDraft,
    ChannelPinnedCommentTemplate,
    ChannelPlaylist,
    ChannelProfile,
    ChannelScheduleEntry,
    ChannelStrategyRecommendation,
    CommunityPostAsset,
    MediaAsset,
    OperationPackage,
    PackageCoverVariant,
    YoutubeAnalyticsBreakdown,
    YoutubeChannelDailyMetric,
    YoutubeComment,
    YoutubeVideo,
    YoutubeVideoDailyMetric,
    Skill,
    SkillVersion,
)
from zhiju.schemas.channel import (
    ChannelAnalysisReportCreate,
    ChannelDnaVersionCreate,
    ChannelHubUpdate,
    ChannelInitializationDraftUpsert,
    ChannelKeywordCreate,
    ChannelPinnedCommentTemplateCreate,
    ChannelProfileUpsert,
    MediaAssetCreate,
    MediaAssetMetadataUpdate,
    MediaAssetStatusChange,
)
from zhiju.services.identity import ConflictError, _audit
from zhiju.services.settings import list_channel_initialization_rules


class NotFoundError(Exception):
    pass


def _channel(session: Session, channel_id: str, *, lock: bool = False) -> Channel:
    statement = select(Channel).where(Channel.id == channel_id, Channel.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    channel = session.scalar(statement)
    if channel is None:
        raise NotFoundError("频道不存在")
    return channel


def get_channel_detail(session: Session, channel_id: str) -> dict[str, object]:
    channel = _channel(session, channel_id)
    profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel_id))
    keywords = list(
        session.scalars(
            select(ChannelKeyword)
            .where(ChannelKeyword.channel_id == channel_id, ChannelKeyword.status == "active")
            .order_by(ChannelKeyword.keyword_type, ChannelKeyword.weight.desc(), ChannelKeyword.keyword)
        )
    )
    active_dna = session.scalar(
        select(ChannelDnaVersion)
        .where(ChannelDnaVersion.channel_id == channel_id, ChannelDnaVersion.status == "active")
        .order_by(ChannelDnaVersion.version_number.desc())
    )
    dna_payload = None
    if active_dna is not None:
        signals = list(
            session.scalars(
                select(ChannelDnaSignal)
                .where(ChannelDnaSignal.dna_version_id == active_dna.id)
                .order_by(ChannelDnaSignal.signal_type, ChannelDnaSignal.rank_number)
            )
        )
        dna_payload = {**active_dna.__dict__, "signals": signals}
    reports = list(
        session.scalars(
            select(ChannelAnalysisReport)
            .where(ChannelAnalysisReport.channel_id == channel_id)
            .order_by(ChannelAnalysisReport.version_number.desc())
            .limit(10)
        )
    )
    pinned_comments = list(
        session.scalars(
            select(ChannelPinnedCommentTemplate)
            .where(ChannelPinnedCommentTemplate.channel_id == channel_id)
            .order_by(
                ChannelPinnedCommentTemplate.language,
                ChannelPinnedCommentTemplate.version_number.desc(),
            )
        )
    )
    playlists = list(
        session.scalars(
            select(ChannelPlaylist)
            .where(
                ChannelPlaylist.channel_id == channel_id,
                ChannelPlaylist.status != "deleted",
            )
            .order_by(ChannelPlaylist.sort_order, ChannelPlaylist.created_at)
        )
    )
    branding_assets = list(
        session.scalars(
            select(ChannelBrandingAsset)
            .where(ChannelBrandingAsset.channel_id == channel_id)
            .order_by(ChannelBrandingAsset.created_at.desc())
        )
    )
    drama_types = list(
        session.scalars(
            select(ChannelDramaType)
            .where(ChannelDramaType.status == "active")
            .order_by(ChannelDramaType.sort_order, ChannelDramaType.name)
        )
    )
    skills = list(
        session.scalars(
            select(Skill)
            .where(
                Skill.status == "active",
                (Skill.category.like("channel%")) | (Skill.code.like("channel-%")),
            )
            .order_by(Skill.category, Skill.name)
        )
    )
    relevant_skills: list[dict[str, object]] = []
    for skill in skills:
        current = session.scalar(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill.id,
                SkillVersion.is_current.is_(True),
            )
        )
        relevant_skills.append(
            {
                "skill_id": skill.id,
                "code": skill.code,
                "name": skill.name,
                "category": skill.category,
                "version_id": current.id if current else None,
                "version_number": current.version_number if current else None,
                "version_status": current.status if current else None,
            }
        )
    return {
        "channel": channel,
        "profile": profile,
        "keywords": keywords,
        "active_dna": dna_payload,
        "recent_reports": reports,
        "pinned_comment_templates": pinned_comments,
        "playlists": playlists,
        "branding_assets": branding_assets,
        "drama_types": drama_types,
        "relevant_skills": relevant_skills,
    }


def get_channel_initialization_readiness(
    session: Session, channel_id: str
) -> dict[str, object]:
    channel = _channel(session, channel_id)
    required_inputs = (
        ("频道名", channel.original_name),
        ("YouTube Channel ID", channel.youtube_channel_id),
        ("频道中文意思", channel.chinese_meaning),
        ("初始题材", channel.default_genre),
        ("短剧类型", channel.drama_type),
    )
    missing_inputs = [label for label, value in required_inputs if not value]
    rules = list_channel_initialization_rules(session)
    missing_rule_modules = [
        rule["module_name"] for rule in rules if rule["readiness"] != "ready"
    ]
    return {
        "channel_id": channel.id,
        "can_initialize": not missing_inputs and not missing_rule_modules,
        "missing_inputs": missing_inputs,
        "missing_rule_modules": missing_rule_modules,
        "rules": rules,
    }


def get_channel_initialization_draft(
    session: Session, channel_id: str
) -> ChannelInitializationDraft | None:
    _channel(session, channel_id)
    return session.scalar(
        select(ChannelInitializationDraft).where(
            ChannelInitializationDraft.channel_id == channel_id
        )
    )


def upsert_channel_initialization_draft(
    session: Session,
    channel_id: str,
    payload: ChannelInitializationDraftUpsert,
) -> ChannelInitializationDraft:
    channel = _channel(session, channel_id, lock=True)
    draft = session.scalar(
        select(ChannelInitializationDraft)
        .where(ChannelInitializationDraft.channel_id == channel_id)
        .with_for_update()
    )
    snapshot = {
        "original_name": channel.original_name,
        "youtube_channel_id": channel.youtube_channel_id,
        "youtube_channel_url": channel.youtube_channel_url,
        "chinese_meaning": channel.chinese_meaning,
        "default_genre": channel.default_genre,
        "drama_type": channel.drama_type,
        "default_language": channel.default_language,
    }
    if draft is None:
        draft = ChannelInitializationDraft(
            channel_id=channel_id,
            input_snapshot=snapshot,
            output_draft=payload.model_dump(),
        )
        session.add(draft)
    else:
        draft.input_snapshot = snapshot
        draft.output_draft = payload.model_dump()
    session.flush()
    _audit(session, "channel_initialization_draft.saved", "channel", channel_id)
    session.commit()
    session.refresh(draft)
    return draft


def apply_channel_initialization_draft(
    session: Session, channel_id: str
) -> dict[str, object]:
    channel = _channel(session, channel_id, lock=True)
    draft = session.scalar(
        select(ChannelInitializationDraft)
        .where(ChannelInitializationDraft.channel_id == channel_id)
        .with_for_update()
    )
    if draft is None:
        raise ConflictError("请先保存频道初始化草稿")
    output = draft.output_draft or {}
    applied_modules: list[str] = []
    retained_modules = [
        label
        for key, label in (
            ("initial_audience", "初始用户画像"),
            ("initial_analysis", "初始分析报告"),
            ("operating_reference", "频道运营参考"),
        )
        if output.get(key)
    ]

    profile_fields = (
        "description",
        "avatar_prompt",
        "banner_prompt",
        "title_template",
        "popup_scheme",
    )
    if any(output.get(field) for field in profile_fields):
        profile = session.scalar(
            select(ChannelProfile).where(ChannelProfile.channel_id == channel_id)
        )
        if profile is None:
            profile = ChannelProfile(channel_id=channel_id, status="draft")
            session.add(profile)
        for field in profile_fields:
            if output.get(field) is not None:
                setattr(profile, field, output[field])
        applied_modules.append("频道说明与装修")

    created_keywords = 0
    language = channel.default_language or "und"
    for keyword_type, values in (
        ("keyword", output.get("keywords") or []),
        ("tag", output.get("tags") or []),
    ):
        for value in values:
            existing = session.scalar(
                select(ChannelKeyword).where(
                    ChannelKeyword.channel_id == channel_id,
                    ChannelKeyword.keyword == value,
                    ChannelKeyword.keyword_type == keyword_type,
                    ChannelKeyword.language == language,
                )
            )
            if existing is None:
                session.add(
                    ChannelKeyword(
                        channel_id=channel_id,
                        keyword=value,
                        keyword_type=keyword_type,
                        language=language,
                        weight=Decimal("0.5000"),
                        source="channel_initialization",
                        effective_from=datetime.now(timezone.utc),
                        status="active",
                    )
                )
                created_keywords += 1
    if output.get("keywords") or output.get("tags"):
        applied_modules.append("关键词与标签")

    created_pinned_comments = 0
    pinned_body = output.get("pinned_comment")
    if pinned_body:
        pinned = session.scalar(
            select(ChannelPinnedCommentTemplate).where(
                ChannelPinnedCommentTemplate.channel_id == channel_id,
                ChannelPinnedCommentTemplate.language == language,
                ChannelPinnedCommentTemplate.body == pinned_body,
            )
        )
        if pinned is None:
            next_version = (
                session.scalar(
                    select(
                        func.coalesce(
                            func.max(ChannelPinnedCommentTemplate.version_number), 0
                        )
                    ).where(
                        ChannelPinnedCommentTemplate.channel_id == channel_id,
                        ChannelPinnedCommentTemplate.language == language,
                    )
                )
                + 1
            )
            pinned = ChannelPinnedCommentTemplate(
                channel_id=channel_id,
                language=language,
                version_number=next_version,
                body=pinned_body,
                status="draft",
            )
            session.add(pinned)
            session.flush()
            created_pinned_comments = 1
        if pinned.status != "active":
            _activate_pinned_comment_template(session, pinned, datetime.now(timezone.utc))
        applied_modules.append("置顶评论")

    created_playlists = 0
    for index, name in enumerate(output.get("playlists") or [], start=1):
        existing = session.scalar(
            select(ChannelPlaylist).where(
                ChannelPlaylist.channel_id == channel_id,
                ChannelPlaylist.local_name == name,
                ChannelPlaylist.status != "deleted",
            )
        )
        if existing is None:
            session.add(
                ChannelPlaylist(
                    channel_id=channel_id,
                    local_name=name,
                    sort_order=index,
                    status="draft",
                )
            )
            created_playlists += 1
    if output.get("playlists"):
        applied_modules.append("播放列表")

    try:
        session.flush()
        _audit(session, "channel_initialization_draft.applied", "channel", channel_id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("频道初始化草稿应用失败") from exc
    return {
        "channel_id": channel_id,
        "applied_modules": applied_modules,
        "retained_draft_modules": retained_modules,
        "created_keywords": created_keywords,
        "created_pinned_comments": created_pinned_comments,
        "created_playlists": created_playlists,
    }


def update_channel_hub(
    session: Session, channel_id: str, payload: ChannelHubUpdate
) -> dict[str, object]:
    channel = _channel(session, channel_id, lock=True)
    values = payload.model_dump(exclude_unset=True)
    if "drama_type" in values and values["drama_type"]:
        drama_type = session.scalar(
            select(ChannelDramaType).where(
                ChannelDramaType.code == values["drama_type"],
                ChannelDramaType.status == "active",
            )
        )
        if drama_type is None:
            raise ValueError("请选择启用中的短剧类型")

    for field in ("chinese_meaning", "default_genre", "drama_type"):
        if field in values:
            setattr(channel, field, values.pop(field))

    profile = session.scalar(
        select(ChannelProfile).where(ChannelProfile.channel_id == channel_id)
    )
    if profile is None:
        profile = ChannelProfile(channel_id=channel_id, status="draft")
        session.add(profile)
    for field in (
        "description",
        "positioning",
        "avatar_prompt",
        "banner_prompt",
        "popup_scheme",
        "title_template",
        "fixed_symbol",
    ):
        if field in values:
            setattr(profile, field, values[field])

    session.flush()
    _audit(session, "channel_hub.updated", "channel", channel.id)
    session.commit()
    return get_channel_detail(session, channel_id)


def upsert_profile(session: Session, channel_id: str, payload: ChannelProfileUpsert) -> ChannelProfile:
    _channel(session, channel_id, lock=True)
    _require_channel_profile_asset(
        session, channel_id, payload.avatar_asset_id, "channel_avatar", "头像"
    )
    _require_channel_profile_asset(
        session, channel_id, payload.banner_asset_id, "channel_banner", "Banner"
    )
    profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel_id))
    if profile is None:
        profile = ChannelProfile(channel_id=channel_id, **payload.model_dump())
        session.add(profile)
        action = "channel_profile.created"
    else:
        for field, value in payload.model_dump().items():
            setattr(profile, field, value)
        action = "channel_profile.updated"
    try:
        session.flush()
        _audit(session, action, "channel_profile", profile.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("头像或Banner资产引用无效") from exc
    session.refresh(profile)
    return profile


def add_keyword(session: Session, channel_id: str, payload: ChannelKeywordCreate) -> ChannelKeyword:
    _channel(session, channel_id)
    keyword = ChannelKeyword(
        channel_id=channel_id,
        **payload.model_dump(),
        effective_from=datetime.now(timezone.utc),
        status="active",
    )
    session.add(keyword)
    try:
        session.flush()
        _audit(session, "channel_keyword.created", "channel_keyword", keyword.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("相同频道、语言和类型的词条已存在") from exc
    session.refresh(keyword)
    return keyword


def deactivate_keyword(
    session: Session, channel_id: str, keyword_id: str
) -> ChannelKeyword:
    _channel(session, channel_id, lock=True)
    keyword = session.scalar(
        select(ChannelKeyword)
        .where(
            ChannelKeyword.id == keyword_id,
            ChannelKeyword.channel_id == channel_id,
        )
        .with_for_update()
    )
    if keyword is None:
        raise NotFoundError("频道关键词或标签不存在")
    if keyword.status == "active":
        keyword.status = "inactive"
        keyword.effective_to = datetime.now(timezone.utc)
        _audit(session, "channel_keyword.deactivated", "channel_keyword", keyword.id)
        session.commit()
        session.refresh(keyword)
    return keyword


def _activate_pinned_comment_template(
    session: Session,
    template: ChannelPinnedCommentTemplate,
    now: datetime,
) -> None:
    active_templates = list(
        session.scalars(
            select(ChannelPinnedCommentTemplate)
            .where(
                ChannelPinnedCommentTemplate.channel_id == template.channel_id,
                ChannelPinnedCommentTemplate.language == template.language,
                ChannelPinnedCommentTemplate.status == "active",
                ChannelPinnedCommentTemplate.id != template.id,
            )
            .with_for_update()
        )
    )
    for active in active_templates:
        active.status = "superseded"
        active.effective_to = now
    template.status = "active"
    template.effective_from = now
    template.effective_to = None


def create_pinned_comment_template(
    session: Session,
    channel_id: str,
    payload: ChannelPinnedCommentTemplateCreate,
) -> ChannelPinnedCommentTemplate:
    _channel(session, channel_id, lock=True)
    language = payload.language.strip().lower()
    next_version = (
        session.scalar(
            select(func.coalesce(func.max(ChannelPinnedCommentTemplate.version_number), 0)).where(
                ChannelPinnedCommentTemplate.channel_id == channel_id,
                ChannelPinnedCommentTemplate.language == language,
            )
        )
        + 1
    )
    template = ChannelPinnedCommentTemplate(
        channel_id=channel_id,
        language=language,
        version_number=next_version,
        body=payload.body.strip(),
        status="draft",
    )
    session.add(template)
    try:
        session.flush()
        if payload.activate:
            _activate_pinned_comment_template(session, template, datetime.now(timezone.utc))
        _audit(
            session,
            "channel_pinned_comment_template.created",
            "channel_pinned_comment_template",
            template.id,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("置顶评论模板版本冲突") from exc
    session.refresh(template)
    return template


def list_pinned_comment_templates(
    session: Session,
    channel_id: str,
    *,
    language: str | None = None,
    status: str | None = None,
) -> list[ChannelPinnedCommentTemplate]:
    _channel(session, channel_id)
    statement = select(ChannelPinnedCommentTemplate).where(
        ChannelPinnedCommentTemplate.channel_id == channel_id
    )
    if language:
        statement = statement.where(
            ChannelPinnedCommentTemplate.language == language.strip().lower()
        )
    if status:
        statement = statement.where(ChannelPinnedCommentTemplate.status == status)
    return list(
        session.scalars(
            statement.order_by(
                ChannelPinnedCommentTemplate.language,
                ChannelPinnedCommentTemplate.version_number.desc(),
            )
        )
    )


def activate_pinned_comment_template(
    session: Session,
    channel_id: str,
    template_id: str,
) -> ChannelPinnedCommentTemplate:
    _channel(session, channel_id, lock=True)
    template = session.scalar(
        select(ChannelPinnedCommentTemplate)
        .where(
            ChannelPinnedCommentTemplate.id == template_id,
            ChannelPinnedCommentTemplate.channel_id == channel_id,
        )
        .with_for_update()
    )
    if template is None:
        raise NotFoundError("置顶评论模板不存在")
    if template.status == "archived":
        raise ConflictError("已归档模板不能激活")
    if template.status != "active":
        _activate_pinned_comment_template(session, template, datetime.now(timezone.utc))
        _audit(
            session,
            "channel_pinned_comment_template.activated",
            "channel_pinned_comment_template",
            template.id,
        )
        session.commit()
        session.refresh(template)
    return template


def create_report(
    session: Session, channel_id: str, payload: ChannelAnalysisReportCreate
) -> dict[str, object]:
    _channel(session, channel_id, lock=True)
    if payload.period_start and payload.period_end and payload.period_start > payload.period_end:
        raise ConflictError("分析周期开始时间不能晚于结束时间")
    for evidence in payload.evidence:
        _validate_report_evidence(session, channel_id, evidence.source_type, evidence.source_entity_id)
    next_version = (
        session.scalar(
            select(func.coalesce(func.max(ChannelAnalysisReport.version_number), 0)).where(
                ChannelAnalysisReport.channel_id == channel_id
            )
        )
        + 1
    )
    report_values = payload.model_dump(
        exclude={"topic_scores", "keyword_scores", "audience_profiles", "strategy_recommendations", "evidence"}
    )
    report = ChannelAnalysisReport(
        channel_id=channel_id,
        version_number=next_version,
        **report_values,
    )
    session.add(report)
    try:
        session.flush()
        session.add_all(
            [ChannelAnalysisTopicScore(report_id=report.id, **item.model_dump()) for item in payload.topic_scores]
        )
        session.add_all(
            [ChannelAnalysisKeywordScore(report_id=report.id, **item.model_dump()) for item in payload.keyword_scores]
        )
        session.add_all(
            [ChannelAudienceProfile(report_id=report.id, **item.model_dump()) for item in payload.audience_profiles]
        )
        session.add_all(
            [
                ChannelStrategyRecommendation(report_id=report.id, **item.model_dump())
                for item in payload.strategy_recommendations
            ]
        )
        session.add_all(
            [ChannelAnalysisEvidence(report_id=report.id, **item.model_dump()) for item in payload.evidence]
        )
        session.flush()
        _audit(session, "channel_analysis_report.created", "channel_analysis_report", report.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("分析报告版本或结构化明细数据冲突") from exc
    return get_report_detail(session, channel_id, report.id)


def _validate_report_evidence(
    session: Session, channel_id: str, source_type: str, source_entity_id: str
) -> None:
    if source_type == "manual":
        return
    model_by_type = {
        "channel_metric": YoutubeChannelDailyMetric,
        "video_metric": YoutubeVideoDailyMetric,
        "analytics_breakdown": YoutubeAnalyticsBreakdown,
        "youtube_video": YoutubeVideo,
        "comment": YoutubeComment,
        "operation_package": OperationPackage,
        "schedule": ChannelScheduleEntry,
        "channel_dna": ChannelDnaVersion,
    }
    entity = session.get(model_by_type[source_type], source_entity_id)
    if entity is None:
        raise ConflictError(f"分析证据不存在: {source_type}/{source_entity_id}")
    if source_type == "video_metric":
        video = session.get(YoutubeVideo, entity.video_id)
        evidence_channel_id = video.channel_id if video else None
    else:
        evidence_channel_id = entity.channel_id
    if evidence_channel_id != channel_id:
        raise ConflictError("分析证据不属于当前频道")


def _report_detail(session: Session, report: ChannelAnalysisReport) -> dict[str, object]:
    report_id = report.id
    return {
        **report.__dict__,
        "topic_scores": list(
            session.scalars(
                select(ChannelAnalysisTopicScore)
                .where(ChannelAnalysisTopicScore.report_id == report_id)
                .order_by(ChannelAnalysisTopicScore.rank_number, ChannelAnalysisTopicScore.topic)
            )
        ),
        "keyword_scores": list(
            session.scalars(
                select(ChannelAnalysisKeywordScore)
                .where(ChannelAnalysisKeywordScore.report_id == report_id)
                .order_by(ChannelAnalysisKeywordScore.rank_number, ChannelAnalysisKeywordScore.keyword)
            )
        ),
        "audience_profiles": list(
            session.scalars(
                select(ChannelAudienceProfile)
                .where(ChannelAudienceProfile.report_id == report_id)
                .order_by(ChannelAudienceProfile.profile_type, ChannelAudienceProfile.rank_number)
            )
        ),
        "strategy_recommendations": list(
            session.scalars(
                select(ChannelStrategyRecommendation)
                .where(ChannelStrategyRecommendation.report_id == report_id)
                .order_by(ChannelStrategyRecommendation.priority, ChannelStrategyRecommendation.category)
            )
        ),
        "evidence": list(
            session.scalars(
                select(ChannelAnalysisEvidence)
                .where(ChannelAnalysisEvidence.report_id == report_id)
                .order_by(ChannelAnalysisEvidence.source_type, ChannelAnalysisEvidence.created_at)
            )
        ),
    }


def list_reports(session: Session, channel_id: str) -> list[dict[str, object]]:
    _channel(session, channel_id)
    reports = list(
        session.scalars(
            select(ChannelAnalysisReport)
            .where(ChannelAnalysisReport.channel_id == channel_id)
            .order_by(ChannelAnalysisReport.version_number.desc())
        )
    )
    return [_report_detail(session, report) for report in reports]


def get_report_detail(session: Session, channel_id: str, report_id: str) -> dict[str, object]:
    _channel(session, channel_id)
    report = session.scalar(
        select(ChannelAnalysisReport).where(
            ChannelAnalysisReport.id == report_id,
            ChannelAnalysisReport.channel_id == channel_id,
        )
    )
    if report is None:
        raise NotFoundError("频道分析报告不存在")
    return _report_detail(session, report)


def create_dna_version(
    session: Session, channel_id: str, payload: ChannelDnaVersionCreate
) -> tuple[ChannelDnaVersion, list[ChannelDnaSignal]]:
    _channel(session, channel_id, lock=True)
    next_version = (
        session.scalar(
            select(func.coalesce(func.max(ChannelDnaVersion.version_number), 0)).where(
                ChannelDnaVersion.channel_id == channel_id
            )
        )
        + 1
    )
    now = datetime.now(timezone.utc)
    if payload.activate:
        current = list(
            session.scalars(
                select(ChannelDnaVersion).where(
                    ChannelDnaVersion.channel_id == channel_id,
                    ChannelDnaVersion.status == "active",
                )
            )
        )
        for version in current:
            version.status = "superseded"
            version.effective_to = now
    values = payload.model_dump(exclude={"activate", "signals"})
    version = ChannelDnaVersion(
        channel_id=channel_id,
        version_number=next_version,
        status="active" if payload.activate else "draft",
        effective_from=now if payload.activate else None,
        **values,
    )
    session.add(version)
    try:
        session.flush()
        signals = [ChannelDnaSignal(dna_version_id=version.id, **item.model_dump()) for item in payload.signals]
        session.add_all(signals)
        _audit(session, "channel_dna_version.created", "channel_dna_version", version.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("DNA版本、分析报告或信号数据冲突") from exc
    session.refresh(version)
    for signal in signals:
        session.refresh(signal)
    return version, signals


def list_dna_versions(session: Session, channel_id: str) -> list[dict[str, object]]:
    _channel(session, channel_id)
    versions = list(
        session.scalars(
            select(ChannelDnaVersion)
            .where(ChannelDnaVersion.channel_id == channel_id)
            .order_by(ChannelDnaVersion.version_number.desc())
        )
    )
    result = []
    for version in versions:
        signals = list(
            session.scalars(
                select(ChannelDnaSignal)
                .where(ChannelDnaSignal.dna_version_id == version.id)
                .order_by(ChannelDnaSignal.signal_type, ChannelDnaSignal.rank_number)
            )
        )
        result.append({**version.__dict__, "signals": signals})
    return result


def register_media_asset(session: Session, payload: MediaAssetCreate) -> MediaAsset:
    if payload.channel_id:
        _channel(session, payload.channel_id)
    if payload.operation_package_id:
        package = session.get(OperationPackage, payload.operation_package_id)
        if package is None:
            raise NotFoundError("运营包不存在")
        if payload.channel_id and package.channel_id != payload.channel_id:
            raise ConflictError("媒体资产频道与运营包频道不一致")
    provider = payload.storage_provider.strip().lower()
    storage_key = payload.storage_key.strip()
    existing = session.scalar(
        select(MediaAsset).where(
            MediaAsset.storage_provider == provider,
            MediaAsset.storage_key == storage_key,
        )
    )
    if existing is not None:
        if existing.sha256 == payload.sha256.lower():
            return existing
        raise ConflictError("相同存储位置已经登记为不同文件")
    values = payload.model_dump()
    values.update(
        storage_provider=provider,
        storage_key=storage_key,
        sha256=payload.sha256.lower(),
    )
    asset = MediaAsset(**values)
    session.add(asset)
    try:
        session.flush()
        _audit(session, "media_asset.registered", "media_asset", asset.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("相同存储位置的资产已经登记") from exc
    session.refresh(asset)
    return asset


def _require_channel_profile_asset(
    session: Session,
    channel_id: str,
    asset_id: str | None,
    expected_role: str,
    label: str,
) -> None:
    if asset_id is None:
        return
    asset = session.get(MediaAsset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise ConflictError(f"{label}资产不存在")
    if (
        asset.channel_id != channel_id
        or asset.asset_type != "image"
        or asset.asset_role != expected_role
        or asset.status != "ready"
    ):
        raise ConflictError(f"{label}必须引用本频道对应用途的可用图片资产")


def _media_asset(session: Session, asset_id: str, *, lock: bool = False) -> MediaAsset:
    statement = select(MediaAsset).where(MediaAsset.id == asset_id)
    if lock:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise NotFoundError("媒体资产不存在")
    return row


def list_media_assets(
    session: Session,
    *,
    channel_id: str | None = None,
    operation_package_id: str | None = None,
    asset_type: str | None = None,
    asset_role: str | None = None,
    status: str | None = None,
    sha256: str | None = None,
    include_deleted: bool = False,
    limit: int = 200,
) -> list[MediaAsset]:
    statement = select(MediaAsset)
    if not include_deleted:
        statement = statement.where(MediaAsset.deleted_at.is_(None))
    for column, value in (
        (MediaAsset.channel_id, channel_id),
        (MediaAsset.operation_package_id, operation_package_id),
        (MediaAsset.asset_type, asset_type),
        (MediaAsset.asset_role, asset_role),
        (MediaAsset.status, status),
        (MediaAsset.sha256, sha256.lower() if sha256 else None),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return list(
        session.scalars(statement.order_by(MediaAsset.created_at.desc()).limit(limit))
    )


def get_media_asset(session: Session, asset_id: str) -> MediaAsset:
    return _media_asset(session, asset_id)


def update_media_asset_metadata(
    session: Session, asset_id: str, payload: MediaAssetMetadataUpdate
) -> MediaAsset:
    asset = _media_asset(session, asset_id, lock=True)
    if asset.status not in {"pending", "failed"}:
        raise ConflictError("只有待处理或失败的未使用素材可以修改文件元数据")
    if _asset_is_referenced(session, asset.id):
        raise ConflictError("媒体资产已经被业务数据引用，不能修改文件元数据")
    values = payload.model_dump(exclude_unset=True)
    if "sha256" in values and values["sha256"] is not None:
        values["sha256"] = values["sha256"].lower()
    for field, value in values.items():
        setattr(asset, field, value)
    _audit(session, "media_asset.metadata_updated", "media_asset", asset.id)
    session.commit()
    session.refresh(asset)
    return asset


def _asset_is_referenced(session: Session, asset_id: str) -> bool:
    checks = (
        select(ChannelProfile.id).where(
            (ChannelProfile.avatar_asset_id == asset_id)
            | (ChannelProfile.banner_asset_id == asset_id)
        ),
        select(ChannelBrandingAsset.id).where(ChannelBrandingAsset.asset_id == asset_id),
        select(PackageCoverVariant.id).where(PackageCoverVariant.asset_id == asset_id),
        select(CommunityPostAsset.id).where(CommunityPostAsset.asset_id == asset_id),
    )
    return any(session.scalar(statement.limit(1)) is not None for statement in checks)


def _validate_ready_asset(asset: MediaAsset) -> None:
    if asset.asset_type == "image" and (
        not asset.mime_type
        or not asset.mime_type.lower().startswith("image/")
        or asset.width is None
        or asset.height is None
    ):
        raise ConflictError("图片缺少有效MIME类型或尺寸，不能标记为可用")
    if asset.asset_type == "video" and (
        not asset.mime_type
        or not asset.mime_type.lower().startswith("video/")
        or asset.width is None
        or asset.height is None
    ):
        raise ConflictError("视频缺少有效MIME类型或尺寸，不能标记为可用")
    if asset.asset_type == "audio" and (
        not asset.mime_type or not asset.mime_type.lower().startswith("audio/")
    ):
        raise ConflictError("音频缺少有效MIME类型，不能标记为可用")


ASSET_STATUS_TRANSITIONS = {
    "pending": {"ready", "failed", "archived"},
    "ready": {"failed", "archived"},
    "failed": {"pending", "archived"},
    "archived": {"ready"},
    "deleted": set(),
}


def change_media_asset_status(
    session: Session, asset_id: str, payload: MediaAssetStatusChange
) -> MediaAsset:
    asset = _media_asset(session, asset_id, lock=True)
    if payload.status == asset.status:
        return asset
    if payload.status not in ASSET_STATUS_TRANSITIONS.get(asset.status, set()):
        raise ConflictError(f"媒体资产不能从{asset.status}变更为{payload.status}")
    if payload.status == "ready":
        _validate_ready_asset(asset)
    elif _asset_is_referenced(session, asset.id):
        raise ConflictError("媒体资产仍被业务数据引用，不能变更为不可用状态")
    old_status = asset.status
    asset.status = payload.status
    _audit(
        session,
        "media_asset.status_changed",
        "media_asset",
        asset.id,
        change_summary=f"{old_status}->{payload.status};reason={payload.reason or ''}",
    )
    session.commit()
    session.refresh(asset)
    return asset


def delete_media_asset(session: Session, asset_id: str) -> MediaAsset:
    asset = _media_asset(session, asset_id, lock=True)
    if asset.status == "deleted":
        return asset
    if _asset_is_referenced(session, asset.id):
        raise ConflictError("媒体资产仍被业务数据引用，不能删除")
    asset.status = "deleted"
    asset.deleted_at = datetime.now(timezone.utc)
    _audit(session, "media_asset.deleted", "media_asset", asset.id)
    session.commit()
    session.refresh(asset)
    return asset
