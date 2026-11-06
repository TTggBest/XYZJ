from io import BytesIO
import pytest
from openpyxl import Workbook, load_workbook
from zhiju.services.xiaowu_sync import parse_binding, parse_cid, match_binding, export_workbook, BINDING_HEADERS, CID_HEADERS


def xlsx(rows):
    book = Workbook(); sheet = book.active
    for row in rows: sheet.append(row)
    output = BytesIO(); book.save(output); return output.getvalue()


def test_binding_uses_video_schedule_mapping_not_title():
    rows = parse_binding(xlsx([['视频ID','频道ID','标题'],['video1','UC1','不能当作剧名']]), 'input.xlsx')
    result = match_binding(rows, {'video1': {'channel':'UC1','titles':['真正的剧名'],'language':'泰语','source':'频道上架信息 → 排期'} })
    assert result[0]['values'] == ['video1','真正的剧名','译制代运营','泰语']
    assert result[0]['issues'] == []


def test_binding_missing_conflict_and_wrong_channel_are_visible():
    rows = [{'video_id':'v','channel_id':'UC2','file':'x.xlsx','line':2}]
    result = match_binding(rows, {'v':{'channel':'UC1','titles':['甲','乙'],'language':'英语','source':'排期'}})
    assert result[0]['issues']
    assert result[0]['values'][1] == ''
    assert match_binding(rows,{})[0]['issues']


def test_csv_quoted_claimants_bom_multiple_rows_preserved():
    data = '\ufeff片单名,视频链接,禁播方\r\n剧甲,https://youtube.com/watch?v=abc,"FUTURE TV Co,Ltd （未来电视有限公司）"\r\n剧甲,https://youtube.com/watch?v=abc,另一权利方\r\n'.encode()
    rows = parse_cid(data,'泰国.csv')
    assert len(rows)==2
    assert rows[0]['values']==['','杭州小五和她的兄弟们科技有限公司','剧甲','https://youtube.com/watch?v=abc','FUTURE TV Co,Ltd （未来电视有限公司）','']
    book = load_workbook(BytesIO(export_workbook('cid', rows)))
    assert list(next(book.active.values))==CID_HEADERS
    assert book.active.cell(2,2).value=='杭州小五和她的兄弟们科技有限公司'
    assert book.active.cell(2,1).value is None
    assert book.active.cell(2,6).value is None


def test_invalid_row_is_not_silently_dropped_and_export_blocks():
    rows=parse_cid('片单名,视频链接,禁播方\n甲,,乙\n'.encode(),'a.csv')
    assert len(rows)==1 and rows[0]['issues']
    with pytest.raises(ValueError): export_workbook('cid',rows)


def test_binding_export_exact_headers_and_fixed_package():
    rows=[{'values':['abc','剧名','错误套餐','西班牙语'],'issues':[]}]
    book=load_workbook(BytesIO(export_workbook('binding',rows)))
    assert list(next(book.active.values))==BINDING_HEADERS
    assert book.active.cell(2,3).value=='译制代运营'

from test_v14_runs import store
from zhiju.database import TenantSession
from zhiju.models import Channel, Drama
from zhiju.models.operations import ChannelScheduleEntry, Language
from zhiju.models.youtube import YoutubeVideo
from zhiju.services.xiaowu_sync import binding_context
from datetime import date, datetime


def test_database_matches_video_linked_schedule_and_keeps_tenant_scope(store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        channel=s.get(Channel,'channel-a');channel.default_language='th'
        # Existing channels may store language codes before the language catalog is populated.
        schedule=ChannelScheduleEntry(id='schedule-a',channel_id=channel.id,drama_id='drama-a',publish_slot_id='slot-a',publish_date=date(2026,11,4),planned_local_time=datetime(2026,11,4,10),planned_beijing_time=datetime(2026,11,4,11),planned_utc_time=datetime(2026,11,4,3),idempotency_key='small-five')
        s.add(schedule)
        s.add(YoutubeVideo(youtube_video_id='abc123',channel_id=channel.id,schedule_id='schedule-a',title='标题不能当剧名',url='https://youtube.com/watch?v=abc123',privacy_status='public',publish_status='published',source='youtube_sync'))
        s.commit()
        rows=[{'video_id':'abc123','channel_id':'UC-a','file':'source.xlsx','line':2}]
        matched=match_binding(rows,binding_context(s,rows))
        assert matched[0]['values']==['abc123','剧目','译制代运营','泰语']
        assert not matched[0]['issues']
    with TenantSession(store,info={'tenant_id':'tenant-b'}) as s:
        assert binding_context(s,rows)=={}


def test_preview_and_binary_export_http_entry(store):
    from fastapi.testclient import TestClient
    from zhiju.app import create_app
    from zhiju.auth_context import get_tenant_db
    app=create_app()
    def db():
        with TenantSession(store,info={'tenant_id':'tenant-a'}) as s: yield s
    app.dependency_overrides[get_tenant_db]=db
    client=TestClient(app)
    first=('files',('one.csv','片单名,视频链接,禁播方\n甲,https://youtube.com/watch?v=abc,机构甲\n'.encode(),'text/csv'))
    second=('files',('two.csv','片单名,视频链接,禁播方\n乙,https://youtube.com/watch?v=def,机构乙\n'.encode(),'text/csv'))
    response=client.post('/api/v3/xiaowu-sync/preview/cid',files=[first,second])
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview['file_count']==2 and preview['total']==2
    output=client.post('/api/v3/xiaowu-sync/export',json={'kind':'cid','rows':preview['rows']})
    assert output.status_code==200
    book=load_workbook(BytesIO(output.content))
    assert book.active.max_row==3
    assert book.active.cell(3,3).value=='乙'
    assert client.post('/api/v3/xiaowu-sync/preview/cid',files={'files':('bad.csv',b'wrong','text/csv')}).status_code==422


@pytest.mark.parametrize(('stored','expected'), [('巴西葡萄牙语','葡萄牙语'),('印度尼西亚语','印尼语'),('法语','法语')])
def test_xiaowu_language_names_in_preview_and_existing_export_rows(stored,expected):
    rows=[{'video_id':'v','channel_id':'UC','file':'a.xlsx','line':2}]
    preview=match_binding(rows,{'v':{'channel':'UC','titles':['剧名'],'language':stored,'source':'频道上架信息 → 排期'}})
    assert preview[0]['values'][3]==expected
    # Re-export a preview created before the label correction as well.
    book=load_workbook(BytesIO(export_workbook('binding',[{'values':['v','剧名','译制代运营',stored],'issues':[]} ])))
    assert book.active.cell(2,4).value==expected
