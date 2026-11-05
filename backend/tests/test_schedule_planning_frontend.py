from test_auth_frontend_contract import run_node


def test_schedule_planning_entry_previews_and_requires_confirmation_before_save():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
const user={...principal,permissions:[...principal.permissions,'schedule.read','schedule.manage','drama.read']};
const plan={id:'plan-1',channel_id:'c1',status:'ready',input_snapshot:{channel:{id:'c1'},start_date:'2026-11-03',end_date:'2026-11-03',daily_count:1,guidance:{mode:'initial'},candidates:[{id:'d1'}]},result:{rows:[{publish_date:'2026-11-03',publish_slot_id:'s1',drama_id:'d1',slot_type:'main',chinese_title:'重获人生',duration_seconds:7200,planned_beijing_time:'2026-11-04T09:00:00',reason:'女主反击符合定位',plot_evidence:'女主夺回公司',pairing_reason:'首日建立方向'}]}};
let confirm=false;
const page=start(process.argv[1],auth,async(path,options={})=>{
 requests.push([path,options]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(user));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"deployment":"cloud","device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"任意频道","daily_publish_count":1}]');
 if(path==='/api/v3/channels/c1/schedule-plans')return new Response(JSON.stringify([plan]));
 if(path==='/api/v3/schedule-plans/plan-1')return new Response(JSON.stringify(plan));
 if(path==='/api/v3/schedule-plans/plan-1/apply'){plan.status='applied';return new Response(JSON.stringify(plan));}
 return new Response('[]');
},{window:{confirm:()=>confirm}});
for(let i=0;i<8;i++)await page.tick();
const nav={dataset:{view:'schedules'}};
await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?nav:null}});
assert.ok(page.nodes.get('viewRoot').innerHTML.includes('AI 排期'));
function button(action,id=''){return {dataset:{action,id,channelId:'c1'},isConnected:true,disabled:false,closest:s=>s==='[data-action]'?buttonElement:null};}
let buttonElement=button('schedule-planning');
await page.document.emit('click',{target:buttonElement});
assert.ok(page.nodes.get('modalBody').innerHTML.includes('最近规划'));
assert.equal(requests.filter(([p])=>p.endsWith('/apply')).length,0);
buttonElement=button('schedule-plan-view','plan-1');await page.document.emit('click',{target:buttonElement});
assert.ok(page.nodes.get('modalBody').innerHTML.includes('女主夺回公司'));
assert.ok(page.nodes.get('modalBody').innerHTML.includes('冷启动定位（未经数据验证）'));
buttonElement=button('schedule-plan-apply','plan-1');await page.document.emit('click',{target:buttonElement});
assert.equal(requests.filter(([p])=>p.endsWith('/apply')).length,0,'取消确认时不能保存');
confirm=true;await page.document.emit('click',{target:buttonElement});
assert.equal(requests.filter(([p])=>p.endsWith('/apply')).length,1);
assert.ok(page.nodes.get('modalBody').innerHTML.includes('已保存'));
''')


def test_generation_requests_planning_queue_and_distinct_executor_task_type():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
const user={...principal,permissions:[...principal.permissions,'schedule.read','schedule.manage','drama.read']};
const plan={id:'plan-1',channel_id:'c1',status:'queued',input_snapshot:{channel:{id:'c1'},start_date:'2026-11-03',end_date:'2026-11-03',daily_count:1,guidance:{mode:'initial'},candidates:[{id:'d1'}]},result:null};
class FormFixture { constructor(form){this.form=form;} entries(){return Object.entries(this.form.values);} }
const page=start(process.argv[1],auth,async(path,options={})=>{
 requests.push([path,options]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(user));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"deployment":"cloud","device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"任意频道","daily_publish_count":1}]');
 if(path==='/api/v3/v14/executor-session')return new Response('{"host_id":"d1","tenant_id":"t1","account_profile":"current","session_token":"test-only"}');
 if(path==='http://127.0.0.1:19733/prepare')return new Response('{"ready":true,"executor_protocol":5,"host_id":"d1","tenant_id":"t1"}');
 if(path==='http://127.0.0.1:19733/start')return new Response('{"running":true}');
 if(path==='/api/v3/channels/c1/schedule-plans')return new Response(JSON.stringify(options.method==='POST'?plan:[plan]));
 if(path==='/api/v3/schedule-plans/plan-1')return new Response(JSON.stringify(plan));
 return new Response('[]');
},{FormData:FormFixture});
for(let i=0;i<8;i++)await page.tick();
const nav={dataset:{view:'schedules'}};
await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?nav:null}});
const submit={isConnected:true,disabled:false};
const form={id:'schedulePlanForm',dataset:{channelId:'c1'},values:{start_date:'2026-11-03',end_date:'2026-11-03',daily_count:'1'},matches:()=>false,querySelector:()=>submit};
await page.document.emit('submit',{target:form});
const creation=requests.find(([p,o])=>p==='/api/v3/channels/c1/schedule-plans' && o.method==='POST');
assert.ok(creation,JSON.stringify(requests.map(r=>r[0])));
assert.equal(JSON.parse(creation[1].body).daily_count,1);
const startCall=requests.find(([p])=>p==='http://127.0.0.1:19733/start');
assert.ok(startCall);
assert.equal(JSON.parse(startCall[1].body).task_type,'channel_scheduling');
assert.ok(page.nodes.get('modalBody').innerHTML.includes('排队中'));
assert.equal(requests.filter(([p])=>p.endsWith('/apply')).length,0);
''')
