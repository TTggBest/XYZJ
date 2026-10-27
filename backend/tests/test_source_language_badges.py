from datetime import date, datetime, time

import pytest

from test_auth_frontend_contract import run_node
from test_v14_runs import store
from zhiju.database import TenantSession
from zhiju.models import Channel, ChannelPublishSlot, ChannelScheduleEntry, Drama
from zhiju.schemas.drama_library import DramaLibraryPage
from zhiju.schemas.drama_progress import DramaProgressPage
from zhiju.schemas.operations import ChannelSchedulePage, ScheduleOverview
from zhiju.schemas.production import TaskOverview, WorkOrderOverview, PackageOperationOverview
from zhiju.services.drama_library import list_drama_library
from zhiju.services.drama_progress import list_drama_progress
from zhiju.services.operations import list_channel_schedule_page, list_schedule_overview
from zhiju.services.production import list_task_overview, list_work_order_overview
from zhiju.services.package_outputs import list_package_operation_overview


@pytest.mark.parametrize('language', ['zh', 'en', None])
def test_list_responses_preserve_original_language_not_channel_language(store, language):
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as session:
        session.get(Drama, 'drama-a').source_language = language
        session.get(Channel, 'channel-a').default_language = 'ar'
        session.add(ChannelPublishSlot(id='slot-source', channel_id='channel-a', slot_number=1,
            slot_type='main', local_time=time(18), timezone='Asia/Shanghai', status='active'))
        session.add(ChannelScheduleEntry(id='schedule-source', channel_id='channel-a', drama_id='drama-a',
            publish_slot_id='slot-source', publish_date=date(2026, 10, 30),
            planned_local_time=datetime(2026, 10, 30, 18), planned_beijing_time=datetime(2026, 10, 30, 18),
            planned_utc_time=datetime(2026, 10, 30, 10), idempotency_key='schedule-source', status='planned'))
        session.commit()
        rows = [
            DramaLibraryPage.model_validate(list_drama_library(session, page=1, page_size=50)).items[0],
            DramaProgressPage.model_validate(list_drama_progress(session, page=1, page_size=50)).items[0],
            ScheduleOverview.model_validate(list_schedule_overview(session)[0]),
            ChannelSchedulePage.model_validate(list_channel_schedule_page(session, channel_id='channel-a')).items[0],
            TaskOverview.model_validate(list_task_overview(session)[0]),
            WorkOrderOverview.model_validate(list_work_order_overview(session)[0]),
            PackageOperationOverview.model_validate(list_package_operation_overview(session)[0]),
        ]
        for row in rows:
            assert row.model_dump().get('source_language', 'MISSING') == language, type(row).__name__


def test_all_requested_pages_show_only_known_original_language_badges():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const items=['zh','en',null,'fr'].map((language,i)=>({id:'d'+i,drama_id:'d'+i,
  drama_number:i,drama_code:'DRM-'+i,business_drama_id:'DRM-'+i,chinese_title:'剧目'+i,
  source_language:language,language:'ar',channel_language:'en',channel_id:'c',channel_name:'英语频道',
  schedule_id:'s'+i,task_id:'t'+i,package_id:'p'+i,source_complete:true,
  task_status:'pending_dispatch',slot_type:'main',slot_local_time:'18:00',
  drama_production_status:'completed',community_count:0,nodes:[],package_status:'building'}));
const paged={items,total:4,page:1,page_size:50,pages:1,summary:{total:4,active:4,expiring:0,archived:0}};
const page=start(process.argv[1],auth,async(path)=>{
  if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
  if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
  if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
  if(path==='/api/v3/workflow-versions')return new Response('{"versions":[],"default_id":"builtin-v14"}');
  if(path.startsWith('/api/v3/dramas/library')||path.startsWith('/api/v3/drama-production')||path.startsWith('/api/v3/schedules/channel-view'))return new Response(JSON.stringify(paged));
  if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c","display_name":"英语频道"}]');
  if(path.startsWith('/api/v3/schedules/overview')||path.startsWith('/api/v3/tasks/overview')||path.startsWith('/api/v3/packages/operations-overview'))return new Response(JSON.stringify(items));
  return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(dataset,selector='[data-view]'){
  await page.document.emit('click',{target:{closest:s=>s===selector?{dataset,closest:()=>null}:null}});
  for(let i=0;i<3;i++)await page.tick();
}
function badges(surface){
  const html=page.nodes.get('viewRoot').innerHTML;
  assert.equal((html.match(/原片·中文/g)||[]).length,1,surface+' Chinese');
  assert.equal((html.match(/原片·英语/g)||[]).length,1,surface+' English');
  assert.equal((html.match(/class="[^"]*source-language-badge/g)||[]).length,2,surface+' missing/unknown hidden');
}
for(const view of ['dramas','workorders','packages','schedules']){await click({view});badges(view);}
for(const mode of ['full','all-day']){await click({action:'schedule-view-mode',mode},'[data-action]');badges(mode);}
await click({action:'go-drama-progress'},'[data-action]');badges('drama progress');
""")
