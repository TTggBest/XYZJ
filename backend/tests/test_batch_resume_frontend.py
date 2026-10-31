from test_auth_frontend_contract import run_node

BOOT = r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[],toasts=[];
let failedRun='',offline=false,wakeOffline=false,onResume=async()=>{};
const tasks=['interrupted','interrupted','running','queued','text_ready','needs_user_review'].map((status,i)=>({
 task_id:'t'+i,work_order_id:'w'+i,execution_run_id:'r'+i,execution_status:status,
 task_status:'dispatched',chinese_title:'drama'+i,nodes:{},progress_percent:25}));
class FixtureFormData {constructor(form){this.form=form;}entries(){return Object.entries(this.form.values);}}
const page=start(process.argv[1],auth,async(path,opts={})=>{
 requests.push([path,opts]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false}');
 if(path.includes('/workflow-versions'))return new Response('{"versions":[]}');
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify(tasks));
 if(path==='/api/v3/v14/executor-session')return new Response('{"host_id":"device-a","tenant_id":"t1","session_token":"test-only"}');
 if(path.startsWith('http://127.0.0.1:19733/')){
  if(offline || (wakeOffline&&path.endsWith('/start')))throw new TypeError('offline');
  return new Response('{"ready":true,"host_id":"device-a","tenant_id":"t1","running":false}');
 }
 if(path.endsWith('/resume')){
  await onResume(path);
  if(path.includes('/'+failedRun+'/')&&failedRun)return new Response('{"detail":"状态已变化"}',{status:409});
  return new Response('{"status":"queued"}');
 }
 return new Response('[]');
},{FormData:FixtureFormData});
for(let i=0;i<5;i++)await page.tick();
page.nodes.get('toastStack').appendChild=x=>toasts.push(x.textContent);
async function click(action){const b={dataset:{action},closest:()=>null};await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?b:null}});}
await click('go-workorders');
async function openBatch(){
 await click('v14-resume-all');
 const html=page.nodes.get('modalBody').innerHTML;
 const date=html.match(/name="batch_date" value="([^"]+)"/)[1];
 return {id:'v14BatchResumeForm',values:{batch_date:date,run_ids:'["r0","r1"]'},elements:{stopped_confirmed:{checked:true}}};
}
const submits=form=>page.document.emit('submit',{target:form});
const resumes=()=>requests.filter(([p])=>p.endsWith('/resume'));
const wakes=()=>requests.filter(([p])=>p==='http://127.0.0.1:19733/start');
'''


def test_batch_resume_only_interrupted_work_and_wake_once_without_changing_versions():
    run_node(BOOT + r'''
assert.match(page.nodes.get('viewRoot').innerHTML,/一键恢复/);
assert.equal(resumes().length,0);
const form=await openBatch();
assert.match(page.nodes.get('modalBody').innerHTML,/保留.*已完成/);
assert.equal(resumes().length,0);
await submits(form);
assert.deepEqual(resumes().map(([p])=>p.split('/').at(-2)),['r0','r1']);
for(const [p,o] of resumes())assert.deepEqual(JSON.parse(o.body),{stopped_confirmed:true,retry_content:false});
assert.equal(wakes().length,1);
assert.match(toasts.join('\n'),/恢复.*2/);
assert.equal(requests.filter(([p])=>p.endsWith('/start-v14')||p.endsWith('/v14-runs')).length,0);
''')


def test_batch_resume_reports_partial_failure_and_still_wakes_successful_rows():
    run_node(BOOT + r'''
failedRun='r1';
await submits(await openBatch());
assert.equal(resumes().length,2);assert.equal(wakes().length,1);
assert.match(toasts.join('\n'),/失败 1/);
assert.match(toasts.join('\n'),/状态已变化/);
''')


def test_batch_resume_requires_confirmation_and_preflight_and_blocks_double_submit():
    run_node(BOOT + r'''
const form=await openBatch();form.elements.stopped_confirmed.checked=false;
await submits(form);assert.equal(resumes().length,0);
form.elements.stopped_confirmed.checked=true;offline=true;
await submits(form);assert.equal(resumes().length,0);
offline=false;
let release;onResume=()=>new Promise(resolve=>{release=resolve;});
const pending=submits(form);for(let i=0;i<3;i++)await page.tick();
await submits(form);assert.equal(resumes().length,1);
onResume=async()=>{};release();await pending;
assert.equal(resumes().length,2);assert.equal(wakes().length,1);
''')


def test_batch_resume_date_change_stops_remaining_rows_but_wakes_queued_work():
    run_node(BOOT + r'''
onResume=async()=>{await page.document.emit('change',{target:{id:'workDate',value:'2026-12-05',matches:()=>false}});};
await submits(await openBatch());
assert.equal(resumes().length,1);assert.equal(wakes().length,1);
''')


def test_batch_resume_does_not_claim_running_if_wakeup_fails():
    run_node(BOOT + r'''
wakeOffline=true;await submits(await openBatch());
assert.equal(resumes().length,2);assert.equal(wakes().length,1);
assert.match(toasts.join('\n'),/唤起失败/);
assert.doesNotMatch(toasts.join('\n'),/已开始生产/);
''')


def test_batch_resume_stops_on_account_change_without_waking_other_company():
    run_node(BOOT + r'''
onResume=async()=>{await auth.resolveBootstrap(async()=>({...principal,tenant_id:'t2'}));};
await submits(await openBatch());
assert.equal(resumes().length,1);assert.equal(wakes().length,0);
''')
