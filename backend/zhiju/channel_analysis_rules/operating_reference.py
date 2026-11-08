"""Validate the applied eight-section operating reference from analysis r3."""
SECTIONS = (
    'positioning', 'topics', 'empathy', 'reusable_patterns',
    'title', 'cover', 'scheduling_playlist', 'validation',
)
COLD_START = 'cold_start_hypothesis'


def is_reference_revision(skill):
    return skill.get('label') == 'xy-yt-report-v2' and skill.get('revision', 0) >= 3


def validate_reference(strategy, *, cold_start):
    reference = strategy.get('operating_reference')
    if not isinstance(reference, dict) or set(reference) != set(SECTIONS):
        raise ValueError('运营参考必须包含约定的八栏')
    statuses = {COLD_START} if cold_start else {'data_supported', 'retest'}
    for name in SECTIONS:
        section = reference[name]
        if not isinstance(section, dict) or section.get('status') not in statuses:
            raise ValueError(f'运营参考 {name} 的证据状态不符')
        if not _strings(section.get('evidence')) or not section['evidence']:
            raise ValueError(f'运营参考 {name} 缺少证据入口')
        if name != 'topics' and not _text(section.get('conclusion')):
            raise ValueError(f'运营参考 {name} 缺少结论')
    topics = reference['topics']
    if not all(_strings(topics.get(key)) for key in ('primary', 'secondary', 'counterexamples')) or not _text(topics.get('boundary')):
        raise ValueError('运营参考题材缺少主辅列表、边界或反例列表')
    if strategy.get('content_priority') != topics['primary'] or strategy.get('content_secondary') != topics['secondary']:
        raise ValueError('诊断的主辅题材与运营参考不一致')
    if 'examples' in reference['title'] and not _strings(reference['title']['examples']):
        raise ValueError('运营参考标题示例必须是文字列表')
    if 'playlist_reference' in reference['scheduling_playlist'] and not _text(reference['scheduling_playlist']['playlist_reference']):
        raise ValueError('运营参考播放列表建议必须为文字')
    return reference


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value):
    return isinstance(value, list) and all(_text(item) for item in value)
