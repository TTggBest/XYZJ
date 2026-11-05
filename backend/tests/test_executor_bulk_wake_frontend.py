from test_auth_frontend_contract import run_node

BOOT = r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[],toasts=[];
let running=false,holdStart=null;
const tasks=['queued','running','text_ready','interrupted'].map((status,i)=>({
 task_id:'t'+i,work_order_id:'w'+i,execution_run_id:'r'+i,execution_status:status,
 execution_host_id:'device-a',task_status:'dispatched',chinese_title:'drama'+i,nodes:{}}));
const page=start(process.argv[1],auth,async(path,opts={})=>{
 requests.push([path,opts]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false}');
 if(path.includes('/workflow-versions'))return new Response('{"versions":[]}');
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify(tasks));
 if(path==='/api/v3/v14/executor-session')return new Response('{"host_id":"device-a","tenant_id":"t1","session_token":"test-only"}');
 if(path.startsWith('http://127.0.0.1:19733/')){
  if(path.endsWith('/start')&&holdStart)await holdStart;
  return new Response(JSON.stringify({ready:true,executor_protocol:5,host_id:'device-a',tenant_id:'t1',running}));
 }
 return new Response('[]');
});
for(let i=0;i<5;i++)await page.tick();
page.nodes.get('toastStack').appendChild=x=>toasts.push(x.textContent);
async function click(action){const b={dataset:{action},closest:()=>null};await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?b:null}});}
await click('go-workorders');
const wakes=()=>requests.filter(([p])=>p==='http://127.0.0.1:19733/start');
'''


def test_bulk_wake_only_starts_executor_once_and_does_not_reset_work():
    run_node(BOOT + r'''
assert.match(page.nodes.get('viewRoot').innerHTML,/data-action="v14-wake-all"[^>]*>.*一键唤醒/);
await click('v14-wake-all');
assert.equal(wakes().length,1);
assert.equal(requests.filter(([p])=>p.endsWith('/resume')||p.endsWith('/start-v14')||p.endsWith('/v14-runs')).length,0);
assert.match(toasts.join('\n'),/唤醒/);
''')


def test_bulk_wake_does_not_queue_another_start_while_running():
    run_node(BOOT + r'''
running=true;await click('go-workorders');
assert.match(page.nodes.get('viewRoot').innerHTML,/data-action="v14-wake-all"[^>]*disabled[^>]*>.*执行器运行中/);
await click('v14-wake-all');
assert.equal(wakes().length,0);
''')


def test_bulk_wake_blocks_duplicate_clicks():
    run_node(BOOT + r'''
let release;holdStart=new Promise(resolve=>{release=resolve;});
const first=click('v14-wake-all');for(let i=0;i<3;i++)await page.tick();
await click('v14-wake-all');assert.equal(wakes().length,1);
release();await first;
''')
