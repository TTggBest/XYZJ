from datetime import datetime, timedelta, timezone

import pytest
from test_v14_runs import store
from test_auth_frontend_contract import run_node
from zhiju.database import TenantSession
from zhiju.models.v14 import V14Run
from zhiju.services.production import list_task_overview
from zhiju.services.v14_runs import run_read


@pytest.mark.parametrize('status,age,expected', [('running',0,'running'),('running',120,'interrupted'),('interrupted',0,'interrupted'),('queued',120,'queued'),('needs_user_review',0,'needs_user_review'),('text_ready',0,'text_ready')])
def test_overview_uses_same_execution_state_as_detail(store,status,age,expected):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        run=V14Run(tenant_id='tenant-a',work_order_id='work-a',package_id='package-a',host_id='device-a',account_profile='current',model='test',status=status,input_snapshot={},rules_snapshot={},heartbeat_at=datetime.now(timezone.utc)-timedelta(seconds=age),error='失败原因' if status=='interrupted' else None)
        s.add(run);s.commit()
        row=list_task_overview(s)[0]
        assert row['execution_run_id']==run.id
        assert row['execution_status']==run_read(s,run)['status']==expected
        assert row['execution_error']==run.error


def test_interrupted_row_offers_resume_without_resuming_on_render():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
let resumes=0;
const tasks=['interrupted','running','queued','needs_user_review','text_ready'].map((status,i)=>({task_id:'t'+i,work_order_id:'w'+i,task_status:'dispatched',work_order_status:'running',chinese_title:'drama'+i,execution_run_id:'r'+i,execution_status:status,execution_error:status==='interrupted'?'连接中断':null,progress_percent:50,nodes:{}}));
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false}');
 if(path.includes('/workflow-versions'))return new Response('{"versions":[]}');
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify(tasks));
 if(path.endsWith('/resume'))resumes++;
 return new Response('[]');
});
for(let i=0;i<5;i++)await page.tick();
async function click(action,extra={}){const b={dataset:{action,...extra},closest:()=>null};await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?b:null}});}
await click('go-workorders');
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/已中断/);assert.match(html,/连接中断/);
assert.equal((html.match(/data-action="v14-resume"/g)||[]).length,2);
assert.match(html,/data-id="r0" data-work-id="w0">恢复生产/);
assert.match(html,/data-action="work-detail" data-id="w0">详情/);
assert.match(html,/data-action="work-detail" data-id="w4">查看结果/);
assert.equal(resumes,0);
assert.match(html,/data-id="r3" data-work-id="w3" data-retry-content="true">恢复生产/);
await click('v14-resume',{id:'r0',workId:'w0'});
assert.match(page.nodes.get('modalBody').innerHTML,/保留已完成阶段/);
assert.equal(resumes,0);
await click('v14-resume',{id:'r3',workId:'w3',retryContent:'true'});
assert.match(page.nodes.get('modalBody').innerHTML,/最多3次/);
assert.match(page.nodes.get('modalBody').innerHTML,/name="retry_content" value="true"/);
assert.equal(resumes,0);
''')
