"""First 20 Beijing days of a same-language channel registration batch."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select

from zhiju.models import Channel, ChannelScheduleEntry
from zhiju.models.v14 import V14Setting
from zhiju.services.identity import ConflictError

BEIJING = ZoneInfo('Asia/Shanghai')
CANCELLED = ('cancelled', 'replaced')


def same_language_channels(session, channel_id, language):
    from zhiju.services.schedule_planning import language_aliases, language_code

    aliases = language_aliases(session)
    channels = session.scalars(select(Channel).where(Channel.deleted_at.is_(None),
        (Channel.id == channel_id) | exists(select(ChannelScheduleEntry.id).where(
            ChannelScheduleEntry.channel_id == Channel.id, ChannelScheduleEntry.status.notin_(CANCELLED)))))
    return [channel for channel in channels if language_code(aliases, channel.default_language) == language]


def registration_day(channel):
    """Match the channel list: interpret timezone-less timestamps as UTC."""
    stamp = channel.created_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(BEIJING).date().isoformat()


def identity(language, channel, targets, slots):
    by_id = {slot['id']: slot for slot in slots}
    starts = []
    for target in targets:
        slot = by_id[target['publish_slot_id']]
        local = datetime.combine(
            date.fromisoformat(target['publish_date']),
            time.fromisoformat(slot['local_time']),
            ZoneInfo(slot['timezone']),
        )
        starts.append(local.astimezone(BEIJING).date())
    return {'language': language, 'registered_on': registration_day(channel), 'first_publish_on': min(starts).isoformat()}


def lock_confirmations(session):
    # Match the lock order used by executor_queue and take this before any
    # non-locking reads that could establish an older MySQL snapshot.
    session.scalar(select(V14Setting.id).with_for_update())


def default_uses_batch(session):
    from zhiju.services import skill_catalog
    selected = skill_catalog.default_id(session, skill_catalog.SCHEDULING)
    return any(v['id'] == selected and v['label'] == 'channel-scheduling' and v['revision'] >= 3
               for v in skill_catalog.versions(session, skill_catalog.SCHEDULING))


def reservations(session, channel_id, batch):
    peers = [channel.id for channel in same_language_channels(session, channel_id, batch['language'])
             if registration_day(channel) == batch['registered_on']]
    entries = select(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id.in_(peers),
                                                 ChannelScheduleEntry.status.notin_(CANCELLED))
    earliest = session.scalar(entries.with_only_columns(ChannelScheduleEntry.planned_beijing_time)
                              .order_by(ChannelScheduleEntry.planned_beijing_time).limit(1))
    first = date.fromisoformat(batch['first_publish_on'])
    if earliest:
        first = min(first, earliest.date())
    last = first + timedelta(days=19)
    blocked = session.execute(entries.with_only_columns(
        ChannelScheduleEntry.drama_id, ChannelScheduleEntry.planned_beijing_time).where(
        ChannelScheduleEntry.channel_id != channel_id,
        ChannelScheduleEntry.planned_beijing_time >= first,
        ChannelScheduleEntry.planned_beijing_time < last + timedelta(days=1),
    )).all()
    return first, last, [{'drama_id': drama_id, 'beijing_date': when.date().isoformat()} for drama_id, when in blocked]


def guard_manual(session, channel, drama_id, beijing_time):
    guard_confirmed_rows(session, channel, [
        {'drama_id': drama_id, 'planned_beijing_time': beijing_time.isoformat()},
    ])


def guard_confirmed_rows(session, channel, rows):
    from zhiju.services.schedule_planning import language_aliases, language_code

    language = language_code(language_aliases(session), channel.default_language)
    day = min(row['planned_beijing_time'][:10] for row in rows)
    batch = {'language': language, 'registered_on': registration_day(channel), 'first_publish_on': day}
    _, _, blocked = reservations(session, channel.id, batch)
    check(rows, blocked)


def check(rows, blocked):
    used = {(item['drama_id'], item['beijing_date']) for item in blocked}
    for row in rows:
        if row.get('drama_id') and (row['drama_id'], row['planned_beijing_time'][:10]) in used:
            raise ConflictError('同批同语频道已在同一北京时间日期使用该剧，请换剧后重新预览')
