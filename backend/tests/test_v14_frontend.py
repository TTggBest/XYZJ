import pytest

from test_auth_frontend_contract import run_node

BOOT = r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
const downloads=[];
const detail={work_order:{id:'work-a',status:'queued',production_date:'2026-10-17',target_publish_date:'2026-10-20'},package:{id:'package-a',status:'building'},nodes:[]};
let run=null;
let createError=false;
const page=start(process.argv[1],auth,async(path,opts={})=>{
 requests.push([path,opts]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/work-orders/work-a')return new Response(JSON.stringify(detail));
 if(path.endsWith('/v14-runs/current'))return new Response(JSON.stringify(run));
 if(path==='/api/v3/v14/executor-session')return new Response(JSON.stringify({session_token:'test-only',host_id:'device-a',tenant_id:'t1',account_profile:'current'}));
 if(path.endsWith('/v14-runs')&&opts.method==='POST'){
  if(createError)return new Response('{"detail":"请先配置 V14 执行主机、模型和规则"}',{status:409});
  run={run_id:'run-a',status:'queued',host_id:'device-a',model:'selected-model',attempts:[]};
  return new Response(JSON.stringify(run));
 }
 return new Response('[]');
},{Blob,URL:{createObjectURL:blob=>{downloads.push(blob);return 'blob:fixture';},revokeObjectURL(){}}});
for(let i=0;i<4;i++)await page.tick();
const toasts=[]; page.nodes.get('toastStack').appendChild=item=>toasts.push(item.textContent);
async function click(action,id,extra={}){
 const button={dataset:{action,id,...extra},closest:()=>null};
 await page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
}
"""


def test_run_button_posts_current_work_order_id():
    run_node(BOOT + r"""
await click('work-detail','work-a');
assert.match(page.nodes.get('drawerBody').innerHTML,/运行 V14/);
await click('v14-start','work-a');
assert.equal(requests.filter(([p,o])=>p==='/api/v3/work-orders/work-a/v14-runs'&&o.method==='POST').length,1);
assert.match(page.nodes.get('drawerBody').innerHTML,/selected-model/);
""")


def test_completed_text_keeps_review_pending():
    run_node(BOOT + r"""
detail.package.status='review_pending';
run={run_id:'run-a',status:'text_ready',host_id:'device-a',model:'selected-model',attempts:[]};
await click('work-detail','work-a');
assert.match(page.nodes.get('drawerBody').innerHTML,/待审核/);
assert.match(page.nodes.get('drawerBody').innerHTML,/文本已完成/);
assert.doesNotMatch(page.nodes.get('drawerBody').innerHTML,/已交付/);
""")


def test_missing_configuration_shows_actionable_error():
    run_node(BOOT + r"""
createError=true;
await click('v14-start','work-a');
assert.match(toasts.join('\n'),/请先配置 V14/);
""")


def test_feishu_workorder_sync_entry_remains():
    run_node(BOOT + r"""
await click('go-workorders');
assert.match(page.nodes.get('viewRoot').innerHTML,/sync-feishu-workorders/);
assert.match(page.nodes.get('viewRoot').innerHTML,/一键同步飞书/);
""")


@pytest.mark.parametrize("action,expected", [
    ("dispatch-selected", ["t2"]),
    ("dispatch-all", ["t1", "t2"]),
])
def test_workorder_start_buttons_enqueue_v14_without_extra_click(action, expected):
    boot = BOOT.replace("return new Response('[]');", r"""
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify([
  {task_id:'t1',task_status:'pending_dispatch',nodes:[]},
  {task_id:'t2',task_status:'pending_dispatch',nodes:[]},
  {task_id:'t3',task_status:'completed',nodes:[]}
 ]));
 if(path.endsWith('/start-v14'))return new Response('{"status":"queued","run_id":"r"}');
 return new Response('[]');
""")
    run_node(boot + r"""
await click('go-workorders');
page.document.querySelectorAll=s=>s==='.task-check:checked'?[{value:'t2'}]:[];
await click(ACTION);
const starts=requests.filter(([p,o])=>p.endsWith('/start-v14')&&o.method==='POST');
assert.deepEqual(starts.map(([p])=>p.split('/')[4]),EXPECTED);
assert.equal(requests.filter(([p,o])=>p.endsWith('/dispatch')&&o.method==='POST').length,0);
assert.match(toasts.join('\n'),/V14.*排队/);
""".replace("ACTION", repr(action)).replace("EXPECTED", repr(expected)))


def test_batch_v14_start_prevents_double_click_and_reports_partial_failure():
    boot = BOOT.replace("return new Response('[]');", r"""
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify([
  {task_id:'t1',task_status:'pending_dispatch',nodes:[]},
  {task_id:'t2',task_status:'pending_dispatch',nodes:[]}
 ]));
 if(path.endsWith('/start-v14')){
  if(path.includes('/t1/')){await gate;return new Response('{"status":"queued","run_id":"r1"}');}
  return new Response('{"detail":"缺少当前频道 V14 材料或固定规则"}',{status:409});
 }
 return new Response('[]');
""")
    run_node(boot + r"""
let release;
const gate=new Promise(resolve=>{release=resolve;});
await click('go-workorders');
const first=click('dispatch-all');
await page.tick();
await click('dispatch-all');
assert.equal(requests.filter(([p])=>p.endsWith('/start-v14')).length,1);
release();await first;
assert.equal(requests.filter(([p])=>p.endsWith('/start-v14')).length,2);
assert.match(toasts.join('\n'),/缺少当前频道 V14 材料/);
assert.match(toasts.join('\n'),/V14 已排队 1 条工单，失败 1 条/);
assert.doesNotMatch(toasts.join('\n'),/已开始生产/);
""")


def test_explicit_executor_authorization_downloads_config_without_switching_actor():
    run_node(BOOT + r"""
let filename='';
page.document.createElement=()=>({click(){filename=this.download;},remove(){}});
await click('v14-authorize');
assert.equal(filename,'zhiju-v14-executor.json');
const config=JSON.parse(await downloads[0].text());
assert.equal(config.host_id,'device-a');
assert.equal(config.session_token,'test-only');
assert.equal(auth.current().user_id,'u1');
""")
