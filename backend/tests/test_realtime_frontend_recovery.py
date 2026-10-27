from test_auth_frontend_contract import run_node


BOOT = r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const timers=new Map(); let timerId=0, configFails=false, configReads=0, configGate=null;
const streams=[]; let status='running';
class EventSource {
 constructor(url){this.url=url;this.readyState=0;this.listeners={};streams.push(this);}
 addEventListener(name,fn){this.listeners[name]=fn;}
 close(){this.readyState=2;}
 emit(name){this.listeners[name]?.();}
}
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config'){
  configReads++; if(configFails)throw new TypeError('offline');
  if(configGate)await configGate;
  return new Response('{"enabled":true,"stream_url":"/api/v3/events/stream","device_role":"worker"}');
 }
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/workflow-versions')return new Response('{"default_id":"builtin-v14","versions":[]}');
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify([
  {task_id:'t1',work_order_id:'w1',chinese_title:'测试剧',work_order_status:status,
   nodes:[],progress_percent:status==='completed'?100:33}
 ]));
 return new Response('[]');
},{EventSource,setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},
 clearTimeout:id=>timers.delete(id)});
page.document.querySelector=()=>null;
async function settle(){for(let i=0;i<6;i++)await page.tick();}
async function flush(ms){for(const [id,t] of [...timers])if(t.ms===ms){timers.delete(id);await t.fn();}await settle();}
await settle();
await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?{dataset:{action:'go-workorders'},closest:()=>null}:null}});
await settle();
assert.match(page.nodes.get('viewRoot').innerHTML,/进行中/);
"""


def test_returning_from_browser_history_reconnects_and_updates_progress():
    run_node(BOOT + r"""
await page.window.emit('pagehide');
assert.equal(streams[0].readyState,2);
status='completed';
await page.window.emit('pageshow',{persisted:true});
await settle();await flush(250);
assert.equal(streams.length,2);
assert.match(page.nodes.get('viewRoot').innerHTML,/已完成/);
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
""")


def test_first_stream_open_corrects_changes_missed_before_subscription():
    run_node(BOOT + r"""
status='completed';streams[0].readyState=1;streams[0].emit('open');
await flush(250);
assert.match(page.nodes.get('viewRoot').innerHTML,/已完成/);
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
""")


def test_config_failure_retries_without_manual_refresh():
    run_node(BOOT + r"""
await page.window.emit('pagehide');configFails=true;
await page.window.emit('pageshow',{persisted:true});await settle();
const failedReads=configReads;configFails=false;status='completed';
await flush(3000);
assert.equal(configReads,failedReads+1);
assert.equal(streams.length,2);
streams[1].emit('open');await flush(250);
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
""")


def test_permanently_closed_source_is_recreated_but_transient_error_is_not():
    run_node(BOOT + r"""
streams[0].readyState=0;streams[0].emit('error');await flush(3000);
assert.equal(streams.length,1);
streams[0].readyState=2;streams[0].emit('error');await flush(3000);
assert.equal(streams.length,2);
status='completed';streams[1].emit('open');await flush(250);
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
""")


def test_hidden_page_cancels_retry_and_online_event_recovers_visible_page():
    run_node(BOOT + r"""
streams[0].readyState=2;streams[0].emit('error');
page.document.visibilityState='hidden';await page.document.emit('visibilitychange');
const before=configReads;await flush(3000);assert.equal(configReads,before);
page.document.visibilityState='visible';status='completed';
await page.window.emit('online');await settle();await flush(250);
assert.equal(streams.length,2);
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
""")


def test_event_bursts_do_not_postpone_pending_progress_refresh():
    run_node(BOOT + r"""
streams[0].emit('data.changed');
const first=[...timers.keys()];
for(let i=0;i<20;i++)streams[0].emit('data.changed');
assert.deepEqual([...timers.keys()],first);
status='completed';await flush(250);
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
""")


def test_stale_stream_cannot_refresh_after_page_has_been_closed():
    run_node(BOOT + r"""
await page.window.emit('pagehide');
status='completed';streams[0].emit('open');streams[0].emit('data.changed');await flush(250);
assert.match(page.nodes.get('viewRoot').innerHTML,/进行中/);
""")


def test_late_config_response_from_a_hidden_page_cannot_duplicate_the_connection():
    run_node(BOOT + r"""
await page.window.emit('pagehide');
let release;configGate=new Promise(resolve=>{release=resolve;});
await page.window.emit('pageshow',{persisted:true});await settle();
await page.window.emit('pagehide');configGate=null;
await page.window.emit('pageshow',{persisted:true});await settle();
assert.equal(streams.length,2);
release();await settle();assert.equal(streams.length,2);
status='completed';streams[1].emit('open');await flush(250);
assert.match(page.nodes.get('viewRoot').innerHTML,/100%/);
""")
