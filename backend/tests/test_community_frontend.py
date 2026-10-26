import pytest

from test_auth_frontend_contract import run_node


@pytest.mark.parametrize("kind,view", [("tasks", "go-workorders"), ("schedules", "go-schedules")])
def test_operator_can_adjust_community_from_both_lists_and_wake_only_missing_nodes(kind, view):
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
const row={schedule_id:'schedule-a',task_id:'task-a',work_order_id:'work-a',community_count:0,
 chinese_title:'剧目',task_status:'completed',work_order_status:'completed',schedule_status:'planned',nodes:[]};
const page=start(process.argv[1],auth,async(path,opts={})=>{
 requests.push([path,opts]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"频道"}]');
 if(path.startsWith('/api/v3/tasks/overview')||path.startsWith('/api/v3/schedules/overview'))return new Response(JSON.stringify([row]));
 if(path==='/api/v3/v14/executor-session')return new Response('{"session_token":"fixture","host_id":"d1","tenant_id":"t1"}');
 if(path==='http://127.0.0.1:19733/prepare')return new Response('{"ready":true,"host_id":"d1","tenant_id":"t1"}');
 if(path==='http://127.0.0.1:19733/start')return new Response('{"running":true}');
 if(path.endsWith('/community'))return new Response('{"community_count":1,"run":{"status":"queued"}}');
 return new Response('[]');
},{FormData:class {constructor(form){this.data=form.fixture;} entries(){return Object.entries(this.data)[Symbol.iterator]();}}});
for(let i=0;i<4;i++)await page.tick();
async function click(action,extra={}){
 const button={dataset:{action,...extra},disabled:false,closest:()=>null};
 await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
}
await click(VIEW);
assert.match(page.nodes.get('viewRoot').innerHTML,/调整社群/);
const id=KIND==='tasks'?'task-a':'schedule-a';
await click('edit-community-count',{kind:KIND,id,count:'0',work:'work-a'});
assert.match(page.nodes.get('modalBody').innerHTML,/不重做搜索、标题、封面和说明/);
const form={id:'communityRequirementForm',matches:()=>false,querySelectorAll:()=>[],
 fixture:{entity_kind:KIND,entity_id:id,community_count:'1',has_work:'1'}};
await page.document.emit('submit',{target:form});
const edits=requests.filter(([p,o])=>o.method==='PATCH');
assert.equal(edits.length,1);
assert.equal(edits[0][0],'/api/v3/'+KIND+'/'+id+'/community');
assert.deepEqual(JSON.parse(edits[0][1].body),{community_count:1});
assert.equal(requests.filter(([p])=>p==='http://127.0.0.1:19733/start').length,1);
assert.ok(!requests.some(([p])=>p.endsWith('/start-v14')||p.endsWith('/v14-runs')),'must not recreate the run');
'''.replace("KIND", repr(kind)).replace("VIEW", repr(view)))
