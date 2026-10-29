from test_auth_frontend_contract import run_node


def test_poll_updates_list_and_open_drawer_without_push_and_stops_drawer_after_close():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const timers=new Map();let seq=0,stage=0,detailReads=0;
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path.includes('/workflow-versions'))return new Response('{"versions":[],"default_id":"v16"}');
 if(path.includes('/v14/settings'))return new Response('{}');
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify([{task_id:'t',chinese_title:'live-drama',work_order_id:'w',work_order_status:stage?'completed':'running',progress_percent:stage?100:66,nodes:{}}]));
 if(path==='/api/v3/work-orders/w'){detailReads++;return new Response(JSON.stringify({work_order:{status:stage?'completed':'running'},package:{id:'p',status:stage?'review_pending':'text_ready'},nodes:[{node_type:'community',status:stage?'completed':'queued',attempt_number:1}]}));}
 if(path.endsWith('/v14-runs/current'))return new Response(JSON.stringify({run_id:'r',status:stage?'text_ready':'running',workflow_version:{label:'V16',revision:1}}));
 return new Response('[]');
},{setTimeout:(fn,ms)=>{const id=++seq;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
for(let i=0;i<5;i++)await page.tick();
async function click(action,extra={}){const b={dataset:{action,...extra},closest:()=>null};await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?b:null}});}
await click('go-workorders');await click('work-detail',{id:'w'});
assert.match(page.nodes.get('drawerBody').innerHTML,/说明已完成 · 文本生产中/);
assert.match(page.nodes.get('viewRoot').innerHTML,/66%/);
page.nodes.get('drawerBody').scrollTop=123;
stage=1;
async function poll(){const [id,t]=[...timers].find(([,t])=>t.ms===5000);timers.delete(id);await t.fn();}
await poll();
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
assert.match(page.nodes.get('drawerBody').innerHTML,/已完成/);
assert.doesNotMatch(page.nodes.get('drawerBody').innerHTML,/说明已完成 · 文本生产中/);
assert.equal(page.nodes.get('drawerBody').scrollTop,123);
await page.document.emit('click',{target:{closest:s=>s==='[data-close-drawer]'?{}:null}});
const before=detailReads;await poll();assert.equal(detailReads,before);
page.document.visibilityState='hidden';await page.document.emit('visibilitychange');
assert.equal([...timers.values()].filter(t=>t.ms===5000).length,0);
''')


def test_closed_push_connection_keeps_progress_polling_active():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
let source,seq=0;const timers=new Map();
class Source {constructor(){source=this;this.listeners={};this.readyState=1;}addEventListener(name,fn){this.listeners[name]=fn;}close(){this.readyState=2;}}
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":true,"stream_url":"/events","device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/workflow-versions')return new Response('{"versions":[]}');
 return new Response('[]');
},{EventSource:Source,setTimeout:(fn,ms)=>{const id=++seq;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
for(let i=0;i<5;i++)await page.tick();
const b={dataset:{action:'go-workorders'},closest:()=>null};await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?b:null}});
assert.ok([...timers.values()].some(t=>t.ms===5000));
source.readyState=2;source.listeners.error();
assert.ok([...timers.values()].some(t=>t.ms===5000),'closed push must not stop fallback polling');
''')
