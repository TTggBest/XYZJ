import pytest

from test_auth_frontend_contract import run_node


@pytest.mark.parametrize("mode", ["day", "all-day", "full"])
def test_batch_creates_only_selected_eligible_schedules_in_current_list(mode):
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const posts=[], created=new Set();
const rows=[
 {schedule_id:'s1',schedule_status:'planned',chinese_title:'第一部'},
 {schedule_id:'s2',schedule_status:'confirmed',chinese_title:'第二部'},
 {schedule_id:'s3',schedule_status:'planned',task_id:'existing',chinese_title:'已有工单'},
 {schedule_id:'s4',schedule_status:'cancelled',chinese_title:'已取消'},
 {schedule_id:'s5',schedule_status:'published',chinese_title:'已发布'},
 {schedule_id:'s6',schedule_status:'reserved',chinese_title:'不选中'}
];
const page=start(process.argv[1],auth,async(path,options={})=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"频道"}]');
 const items=rows.map(r=>({...r,task_id:created.has(r.schedule_id)?'new-'+r.schedule_id:r.task_id}));
 if(path.startsWith('/api/v3/schedules/overview'))return new Response(JSON.stringify(items));
 if(path.startsWith('/api/v3/schedules/channel-view'))return new Response(JSON.stringify({page:1,page_size:50,total:200,items}));
 if(options.method==='POST'){
  assert.equal(path,'/api/v3/tasks','must not dispatch, run V14, or write Feishu');
  const body=JSON.parse(options.body); posts.push(body);created.add(body.schedule_id);
  return new Response(JSON.stringify({id:'new-'+body.schedule_id}),{status:201});
 }
 return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(action,extra={}){
 const button={dataset:{action,...extra},disabled:false,closest:()=>null};
 await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
}
await click('go-schedules');
await click('schedule-view-mode',{mode:MODE});
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/批量生成选中工单/);
assert.match(html,/<input[^>]*id="scheduleTaskSelectAll"/);
assert.match(html,/schedule-task-check[^>]*value="s3"[^>]*disabled/);
assert.match(html,/schedule-task-check[^>]*value="s4"[^>]*disabled/);
const boxes=rows.map(r=>({value:r.schedule_id,checked:false,disabled:!!r.task_id||['cancelled','published'].includes(r.schedule_status)}));
page.document.querySelectorAll=s=>s==='.schedule-task-check'?boxes:s==='.schedule-task-check:checked'?boxes.filter(b=>b.checked):[];
await page.document.emit('change',{target:{id:'scheduleTaskSelectAll',checked:true,matches:()=>false}});
assert.deepEqual(boxes.filter(b=>b.checked).map(b=>b.value),['s1','s2','s6']);
boxes.find(b=>b.value==='s6').checked=false;
boxes.find(b=>b.value==='s3').checked=true; // A stale/tampered checkbox must not create another task.
await click('create-selected-tasks');
assert.deepEqual(posts.map(p=>p.schedule_id),['s1','s2']);
assert.equal(posts[0].task_date,posts[1].task_date);
await click('create-selected-tasks');
assert.equal(posts.length,2,'existing tasks must be skipped on retry');
""".replace("MODE", repr(mode)))


@pytest.mark.parametrize("scenario", ["failure", "logout", "change_date"])
def test_batch_handles_failure_logout_date_change_and_double_click(scenario):
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const posts=[],toasts=[];
const rows=[{schedule_id:'s1',chinese_title:'第一部',schedule_status:'planned'},
 {schedule_id:'s2',chinese_title:'第二部',schedule_status:'planned'}];
const page=start(process.argv[1],auth,async(path,options={})=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"频道"}]');
 if(path.startsWith('/api/v3/schedules/overview'))return new Response(JSON.stringify(rows));
 if(options.method==='POST'){
  assert.equal(path,'/api/v3/tasks');
  const body=JSON.parse(options.body);posts.push(body);
  if(posts.length===1){
   await click('create-selected-tasks'); // A rapid second click must do nothing.
   if(SCENARIO==='logout')auth.clear();
   if(SCENARIO==='change_date')await page.document.emit('change',{target:{id:'scheduleDate',value:'2026-11-05',matches:()=>false}});
   if(SCENARIO==='failure')return new Response('{"detail":"频道暂停"}',{status:409});
  }
  return new Response(JSON.stringify({id:'task-'+body.schedule_id}),{status:201});
 }
 return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(action){
 const button={dataset:{action},disabled:false,innerHTML:'批量生成选中工单',closest:()=>null};
 await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
}
page.nodes.get('toastStack').appendChild=toast=>toasts.push(toast.textContent);
await click('go-schedules');
await click('create-selected-tasks');
assert.equal(posts.length,0,'no selection must not create anything');
assert.ok(toasts.some(t=>t.includes('请先勾选')));
page.document.querySelectorAll=s=>s==='.schedule-task-check:checked'?[{value:'s1'},{value:'s2'}]:[];
await click('create-selected-tasks');
assert.equal(posts.length,SCENARIO==='logout'?1:2);
if(SCENARIO==='failure'){
 assert.match(page.nodes.get('modalBody').innerHTML,/成功 1 条，失败 1 条/);
 assert.match(page.nodes.get('modalBody').innerHTML,/第一部：频道暂停/);
}
if(SCENARIO==='change_date'){
 assert.equal(posts[0].task_date,posts[1].task_date,'the batch date must be captured before submission');
 assert.notEqual(posts[1].task_date,'2026-11-05');
}
if(SCENARIO==='logout')assert.equal(toasts.filter(t=>t.includes('批量生成完成')).length,0);
""".replace("SCENARIO", repr(scenario)))
