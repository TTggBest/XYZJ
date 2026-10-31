from sqlalchemy import create_engine, event
from zhiju.database import TenantSession
from zhiju.models import Base, Drama, DramaAlias, DramaProductionState
from zhiju.services.operations import list_schedulable_dramas, SCHEDULABLE_PRODUCTION_FIELDS


def test_eligible_drama_list_batches_related_data():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={'tenant_id': 'tenant-a'}) as session:
        for number in range(5):
            drama = Drama(drama_number=number, drama_code=f'T-{number}', chinese_title=f'剧{number}',
                          normalized_title=f'剧{number}', source_type='manual', status='active')
            session.add(drama)
            session.flush()
            session.add(DramaProductionState(drama_id=drama.id,
                        **{field: 'completed' for field in SCHEDULABLE_PRODUCTION_FIELDS}))
            session.add(DramaAlias(drama_id=drama.id, alias=f'别名{number}', normalized_alias=f'别名{number}', source='manual'))
        session.commit()
        statements = []
        def record(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', record)
        try:
            result = list_schedulable_dramas(session)
        finally:
            event.remove(engine, 'before_cursor_execute', record)
        assert len(result) == 5
        assert all(len(item['aliases']) == 1 for item in result)
        assert len(statements) <= 3, '可排期剧目不应逐部查询别名与核心词'
    engine.dispose()
