"""小五登记文件转换；只读智矩数据，不提交到第三方。"""
import csv
from io import BytesIO, StringIO
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import or_, select

from zhiju.models.identity import Channel
from zhiju.models.operations import ChannelScheduleEntry, Drama, Language
from zhiju.models.youtube import YoutubeVideo
from zhiju.services.feishu_sync import DRAMA_LANGUAGE_COLUMNS

BINDING_HEADERS = ['*视频ID/Video ID', "*作品名称/Works's name", '*运作套餐/Operational Package', '发布语种/Publish language']
CID_HEADERS = ['填写方名称', '授权方', '片单名', '视频链接', '禁播方（如不是被xiaowu匹配，请务必在此列备注）', '授权证明']
AUTHORIZER = '杭州小五和她的兄弟们科技有限公司'
PACKAGE = '译制代运营'
# 小五登记系统接受的语种名称，与频道内部语言标签分开。
XIAOWU_LANGUAGE_NAMES = {'巴西葡萄牙语':'葡萄牙语', '印度尼西亚语':'印尼语'}


def text(value):
    return '' if value is None else str(value).strip()


def parse_binding(content, filename):
    try:
        book = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, ValueError, OSError) as exc:
        raise ValueError(f'{filename}：无法读取 XLSX 文件') from exc
    try:
        sheet = book.active
        values = sheet.iter_rows(values_only=True)
        headers = [text(v) for v in next(values, ())]
        if '视频ID' not in headers:
            raise ValueError(f'{filename}：缺少“视频ID”列')
        result = []
        for line, row in enumerate(values, 2):
            if not any(text(v) for v in row):
                continue
            record = dict(zip(headers, row))
            result.append({'video_id':text(record.get('视频ID')), 'channel_id':text(record.get('频道ID')), 'file':filename, 'line':line})
        if not result:
            raise ValueError(f'{filename}：没有视频数据')
        return result
    finally:
        book.close()


def binding_context(session, rows):
    """按视频登记及关联排期取剧目；不按视频标题模糊匹配。"""
    ids = {r['video_id'] for r in rows if r['video_id']}
    if not ids:
        return {}
    videos = list(session.scalars(select(YoutubeVideo).where(YoutubeVideo.youtube_video_id.in_(ids))))
    schedule_ids = {v.schedule_id for v in videos if v.schedule_id}
    schedules = list(session.scalars(select(ChannelScheduleEntry).where(or_(
        ChannelScheduleEntry.source_video_id.in_(ids), ChannelScheduleEntry.id.in_(schedule_ids)
    ))))
    channel_ids = {v.channel_id for v in videos} | {s.channel_id for s in schedules}
    channels = {c.id:c for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids)))}
    drama_ids = {v.drama_id for v in videos if v.drama_id} | {s.drama_id for s in schedules}
    titles = dict(session.execute(select(Drama.id, Drama.chinese_title).where(Drama.id.in_(drama_ids))).all())
    languages = {value[0]:value[1] for value in DRAMA_LANGUAGE_COLUMNS.values()}
    languages.update(dict(session.execute(select(Language.code, Language.name_zh)).all()))
    result = {}
    for vid in ids:
        matched_videos = [v for v in videos if v.youtube_video_id == vid]
        linked_ids = {v.schedule_id for v in matched_videos if v.schedule_id}
        matched_schedules = [s for s in schedules if s.source_video_id == vid or s.id in linked_ids]
        matches = matched_videos + matched_schedules
        if not matches:
            continue
        linked_channels = {m.channel_id for m in matches}
        channel = channels.get(next(iter(linked_channels))) if len(linked_channels)==1 else None
        names = sorted({titles[m.drama_id] for m in matches if m.drama_id in titles})
        result[vid] = {'channel': channel.youtube_channel_id if channel else '',
                       'titles':names, 'language': languages.get(channel.default_language, '') if channel else '',
                       'source':'频道上架信息 → 排期' if matched_videos and matched_schedules else ('频道上架信息' if matched_videos else '排期视频ID')}
    return result


def match_binding(rows, context):
    result = []
    for row in rows:
        match = context.get(row['video_id'])
        issues = []
        title = language = source = ''
        if not row['video_id']:
            issues.append('视频ID为空')
        elif not match:
            issues.append('智矩未找到该视频的上架信息或排期')
        else:
            source = match['source']
            if not match['channel'] or (row['channel_id'] and row['channel_id'] != match['channel']):
                issues.append('视频所属频道与上传表不一致或存在冲突')
            else:
                if len(match['titles']) != 1:
                    issues.append('未找到唯一对应剧名，请核对视频关联排期')
                else:
                    title = match['titles'][0]
                language = XIAOWU_LANGUAGE_NAMES.get(match['language'], match['language'])
                if not language:
                    issues.append('对应频道未配置发布语种')
        result.append({**row, 'values':[row['video_id'],title,PACKAGE,language], 'source':source, 'issues':issues})
    return result


def parse_cid(content, filename):
    try:
        data = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{filename}：请使用 UTF-8 CSV 文件') from exc
    reader = csv.DictReader(StringIO(data, newline=''))
    if not reader.fieldnames or not {'片单名','视频链接','禁播方'}.issubset(reader.fieldnames):
        raise ValueError(f'{filename}：需要“片单名、视频链接、禁播方”三列')
    result=[]
    for row in reader:
        if not any(text(v) for v in row.values() if isinstance(v,str)):
            continue
        values=[text(row.get(k)) for k in ['片单名','视频链接','禁播方']]
        issues=[f'{k}为空' for k,v in zip(['片单名','视频链接','禁播方'],values) if not v]
        result.append({'file':filename,'line':reader.line_num,'values':['',AUTHORIZER,*values,''],'issues':issues})
    if not result:
        raise ValueError(f'{filename}：没有 CID 数据')
    return result


def export_workbook(kind, rows):
    if kind not in {'binding','cid'} or not rows:
        raise ValueError('没有可导出的数据')
    headers = BINDING_HEADERS if kind=='binding' else CID_HEADERS
    book=Workbook(); sheet=book.active; sheet.title='视频绑定' if kind=='binding' else '解CID'
    sheet.append(headers)
    for row in rows:
        values=[text(v) for v in row['values']]
        if row.get('issues') or len(values)!=len(headers):
            raise ValueError('存在待核对的数据，请先修正后重新上传')
        if kind=='binding':
            values[2]=PACKAGE
            values[3]=XIAOWU_LANGUAGE_NAMES.get(values[3], values[3])
            if not all(values): raise ValueError('视频ID、作品名称和发布语种不能为空')
        else:
            values[0]=''; values[1]=AUTHORIZER; values[5]=''
            if not all(values[2:5]): raise ValueError('片单名、视频链接和禁播方不能为空')
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            cell.data_type='s'
            cell.alignment=Alignment(vertical='center',wrap_text=True)
        if kind=='cid':
            link=sheet.cell(sheet.max_row,4); link.hyperlink=values[3]; link.style='Hyperlink'
    for cell in sheet[1]:
        cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='087F5B')
        cell.alignment=Alignment(vertical='center',wrap_text=True)
    widths=[24,50,28,25] if kind=='binding' else [22,58,48,62,65,25]
    for i,width in enumerate(widths,1): sheet.column_dimensions[sheet.cell(1,i).column_letter].width=width
    sheet.row_dimensions[1].height=34; sheet.freeze_panes='A2'; sheet.auto_filter.ref=sheet.dimensions
    output=BytesIO(); book.save(output); return output.getvalue()
