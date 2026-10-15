import json
from contextlib import contextmanager
from itertools import count
from urllib.parse import unquote

import pytest
from sqlalchemy import create_engine, event

from zhiju.database import TenantSession
from zhiju.models import Base, Drama, DramaProductionState
from zhiju.services import feishu_sync
from zhiju.services.drama_library import list_drama_library, get_drama_library_detail


def test_only_xiaoyu_titles_are_imported_and_master_fields_are_enriched(monkeypatch):
    tables = {
        '筱宇译制': [{'剧名': '入库剧', '百度网盘': 'https://pan.baidu.com/selected', '时长': '01:22:23', '__source_row_number': '8'}],
        '总库表': [
            {'作品名称': '入库剧', '评分': '95.3', '网盘': 'https://pan.baidu.com/master', '到期日期': '2027-07-05', '内容概述': '完整版概述', '剧情档案': '', '核心人设': '大女主'},
            {'作品名称': '不能入库', '评分': '99'},
        ],
        '简表': [{'作品名称': '入库剧', '剧情档案': '补充档案', '内容概述': '简版概述'}],
    }
    class Client:
        def rows_by_title(self, wiki, title, last_column, *, batch_size):
            assert batch_size == 100
            return {'筱宇译制': 'GuSZhU', '总库表': 'LeavcD', '简表': 'nUqvCm'}[title], tables[title]
    monkeypatch.setattr(feishu_sync, '_client', lambda: Client())
    sheet_id, rows = feishu_sync.read_drama_library_rows()
    assert sheet_id == 'GuSZhU'
    assert len(rows) == 1
    assert rows[0]['作品名称'] == '入库剧'
    assert rows[0]['百度网盘链接'] == 'https://pan.baidu.com/selected'
    assert rows[0]['综合评分'] == '95.3'
    assert rows[0]['到期时间'] == '2027-07-05'
    assert rows[0]['内容概述'] == '完整版概述'
    assert rows[0]['剧情档案'] == '补充档案'
    assert rows[0]['核心人设'] == '大女主'
    assert rows[0]['__source_row_number'] == '8'
    assert rows[0]['时长'] == '01:22:23'


@contextmanager
def isolated_session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    numbers = count(1)
    def assign_number(mapper, connection, target):
        # SQLite does not implement MySQL's non-PK auto-increment column.
        if target.drama_number is None:
            target.drama_number = next(numbers)
    event.listen(Drama, 'before_insert', assign_number)
    try:
        with TenantSession(engine, info={'tenant_id': 'tenant-test'}) as session:
            yield session
    finally:
        event.remove(Drama, 'before_insert', assign_number)
        engine.dispose()


def test_sync_roundtrip_only_imports_selected_drama_and_is_idempotent(monkeypatch):
    class Client:
        def rows_by_title(self, wiki, title, last_column, *, batch_size):
            if title == '筱宇译制':
                return 'GuSZhU', [{'剧名': '入库剧', '时长': '31:18', '__source_row_number': '9'}]
            return title, [
                {'作品名称': '入库剧', '评分': '95.3', '到期日期': '2027-07-05', '内容概述': '全本内容'},
                {'作品名称': '外部剧'},
            ]
    monkeypatch.setattr(feishu_sync, '_client', lambda: Client())
    with isolated_session() as session:
        result = feishu_sync.sync_dramas(session)
        page = list_drama_library(session, page=1, page_size=10)
        assert result['rows_inserted'] == 1
        assert page['summary']['total'] == 1
        detail = get_drama_library_detail(session, page['items'][0]['id'])
        assert detail['chinese_title'] == '入库剧'
        assert float(detail['comprehensive_score']) == 95.3
        assert detail['total_duration_seconds'] == 1878
        assert detail['episode_count'] is None
        assert detail['content_summary'] == '全本内容'
        result = feishu_sync.sync_dramas(session)
        assert result['rows_inserted'] == 0
        assert result['rows_updated'] == 0


def test_batched_reads_preserve_headers_and_original_row_numbers(monkeypatch):
    ranges = []
    class Response:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(self.data).encode()
    def urlopen(request, timeout):
        url = unquote(request.full_url)
        if '/auth/' in url:
            return Response({'tenant_access_token': 'fixture'})
        if '/wiki/' in url:
            return Response({'data': {'node': {'obj_token': 'book'}}})
        if '/sheets/query' in url:
            return Response({'data': {'sheets': [{'sheet_id': 'selected', 'title': '筱宇译制', 'grid_properties': {'row_count': 5}}]}})
        cell_range = url.split('/values/')[1].split('?')[0]
        ranges.append(cell_range)
        values = {'selected!A1:K2': [['剧名'], ['甲']], 'selected!A3:K4': [['乙']], 'selected!A5:K5': [['丙']]}[cell_range]
        return Response({'data': {'valueRange': {'values': values}}})
    monkeypatch.setattr(feishu_sync, 'urlopen', urlopen)
    _, rows = feishu_sync.FeishuClient('fixture', 'fixture').rows_by_title('wiki', '筱宇译制', 'K', batch_size=2)
    assert [r['剧名'] for r in rows] == ['甲', '乙', '丙']
    assert [r['__source_row_number'] for r in rows] == ['2', '3', '5']
    assert len(ranges) == 3


def test_sync_preserves_existing_status_batch_and_episode_count_when_source_omits_them(monkeypatch):
    class Client:
        def rows_by_title(self, wiki, title, last_column, *, batch_size):
            if title == '筱宇译制':
                return 'GuSZhU', [{'剧名': '已有剧', '时长': '00:20:00', '__source_row_number': '2'}]
            return title, [{'作品名称': '已有剧'}]
    monkeypatch.setattr(feishu_sync, '_client', lambda: Client())
    with isolated_session() as session:
        drama = Drama(drama_code='existing', chinese_title='已有剧', normalized_title='已有剧', status='archived', batch_name='保留批次')
        session.add(drama)
        session.flush()
        session.add(DramaProductionState(drama_id=drama.id, episode_count=42, is_production_excluded=True))
        session.commit()
        feishu_sync.sync_dramas(session)
        detail = get_drama_library_detail(session, drama.id)
        assert detail['status'] == 'archived'
        assert detail['batch_name'] == '保留批次'
        assert detail['episode_count'] == 42
        assert detail['total_duration_seconds'] == 1200


@pytest.mark.parametrize(('value', 'seconds'), [('31:18', 1878), ('01:22:23', 4943), ('-', None), ('', None)])
def test_actual_selected_sheet_duration_formats(value, seconds):
    assert feishu_sync.parse_operation_duration(value, row_number=74) == seconds
