from test_auth_frontend_contract import run_node


def test_schedule_planning_entry_previews_and_requires_confirmation_before_save():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
const user={...principal,permissions:[...principal.permissions,'schedule.read','schedule.manage','drama.read']};
const plan={id:'plan-1',channel_id:'c1',status:'ready',input_snapshot:{channel:{id:'c1'},start_date:'2026-11-03',end_date:'2026-11-03',daily_count:1,guidance:{mode:'initial'},candidates:[{id:'d1'}],slot_topics:{s1:'secondary'},slots:[{id:'s1',slot_type:'main',slot_number:1}]},result:{rows:[{publish_date:'2026-11-03',publish_slot_id:'s1',drama_id:'d1',slot_type:'main',chinese_title:'重获人生',duration_seconds:7200,planned_beijing_time:'2026-11-04T09:00:00',reason:'女主反击符合定位',plot_evidence:'女主夺回公司',pairing_reason:'首日建立方向'}]}};
let confirm=false;
plan.input_snapshot.selection_evidence={collected_at:'2026-11-12T00:00:00Z',analytics:{recent_7d:{window:{start:'2026-11-05',end:'2026-11-11'},status:'unavailable',rows:[]}}};
plan.result.planning_review={viewer_promises:{primary:'丈夫夺产→女主取证→夺回公司'},compared_candidates:128,total_candidates:129,evidence_review:'已核对真实观看样本',feedback_review:'旧假设待验证',packaging_review:'封面实图未读取',missing_evidence:['开场留存未取得']};
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
assert.ok(page.nodes.get('modalBody').innerHTML.includes('主档 · 辅题材'));
assert.ok(page.nodes.get('modalBody').innerHTML.includes('冷启动定位（未经数据验证）'));
assert.ok(page.nodes.get('modalBody').innerHTML.includes('丈夫夺产→女主取证→夺回公司'));
assert.ok(page.nodes.get('modalBody').innerHTML.includes('已比较 128 / 129 部候选'));
assert.ok(page.nodes.get('modalBody').innerHTML.includes('未取得，非0'));
assert.ok(page.nodes.get('modalBody').innerHTML.includes('封面实图未读取'));
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
const cadence=[
 {daily_publish_count:1,slots:[{id:'m1',slot_type:'main',slot_number:1,local_video_time:'18:00:00'}]},
 {daily_publish_count:2,slots:[{id:'a21',slot_type:'aux',slot_number:1,local_video_time:'10:00:00'},{id:'m2',slot_type:'main',slot_number:2,local_video_time:'18:00:00'}]},
 {daily_publish_count:3,slots:[{id:'a31',slot_type:'aux',slot_number:1,local_video_time:'09:00:00'},{id:'m3',slot_type:'main',slot_number:2,local_video_time:'18:00:00'},{id:'a32',slot_type:'aux',slot_number:3,local_video_time:'13:00:00'}]}
];
let executorProtocol=8;
const page=start(process.argv[1],auth,async(path,options={})=>{
 requests.push([path,options]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(user));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"deployment":"cloud","device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"任意频道","daily_publish_count":1}]');
 if(path==='/api/v3/v14/executor-session')return new Response('{"host_id":"d1","tenant_id":"t1","account_profile":"current","session_token":"test-only"}');
 if(path==='/api/v3/cadence-templates')return new Response(JSON.stringify(cadence));
 if(path==='http://127.0.0.1:19733/prepare')return new Response(JSON.stringify({ready:true,executor_protocol:executorProtocol,host_id:'d1',tenant_id:'t1'}));
 if(path==='http://127.0.0.1:19733/start')return new Response('{"running":true}');
 if(path==='/api/v3/channels/c1/schedule-plans')return new Response(JSON.stringify(options.method==='POST'?plan:[plan]));
 if(path==='/api/v3/schedule-plans/plan-1')return new Response(JSON.stringify(plan));
 return new Response('[]');
},{FormData:FormFixture});
for(let i=0;i<8;i++)await page.tick();
const nav={dataset:{view:'schedules'}};
await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?nav:null}});
const open={dataset:{action:'schedule-planning'},isConnected:true,closest:s=>s==='[data-action]'?open:null};
await page.document.emit('click',{target:open});
const modal=page.nodes.get('modalBody').innerHTML;
assert.ok(modal.includes('name="slot_topic_m1"'));
assert.equal((modal.match(/name="slot_topic_/g)||[]).length,1);
const fields={innerHTML:'',querySelectorAll:()=>[{dataset:{topicSlot:'主档'},value:'secondary'}]};
page.nodes.set('schedulePlanTopics',fields);
const count=Object.assign(page.document.createElement(),{id:'schedulePlanDailyCount',value:'2',matches:()=>false});
await page.document.emit('change',{target:count});
assert.equal((fields.innerHTML.match(/name="slot_topic_/g)||[]).length,2);
assert.match(fields.innerHTML,/slot_topic_m2[^>]*>[\s\S]*?value="secondary" selected/);
count.value='3';
await page.document.emit('change',{target:count});
assert.equal((fields.innerHTML.match(/name="slot_topic_/g)||[]).length,3);
assert.ok(fields.innerHTML.includes('辅档 2'));
const submit={isConnected:true,disabled:false};
const form={id:'schedulePlanForm',dataset:{channelId:'c1'},values:{start_date:'2026-11-03',end_date:'2026-11-03',daily_count:'3',slot_topic_m3:'secondary',slot_topic_a31:'primary',slot_topic_a32:'secondary'},matches:()=>false,querySelector:()=>submit};
await page.document.emit('submit',{target:form});
assert.ok(!requests.some(([p,o])=>p.endsWith('/schedule-plans') && o.method==='POST'));
executorProtocol=9;
await page.document.emit('submit',{target:form});
const creation=requests.find(([p,o])=>p==='/api/v3/channels/c1/schedule-plans' && o.method==='POST');
assert.ok(creation,JSON.stringify(requests.map(r=>r[0])));
assert.equal(JSON.parse(creation[1].body).daily_count,3);
assert.deepEqual(JSON.parse(creation[1].body).slot_topics,{m3:'secondary',a31:'primary',a32:'secondary'});
const startCall=requests.find(([p])=>p==='http://127.0.0.1:19733/start');
assert.ok(startCall);
assert.equal(JSON.parse(startCall[1].body).task_type,'channel_scheduling');
assert.ok(page.nodes.get('modalBody').innerHTML.includes('排队中'));
assert.equal(requests.filter(([p])=>p.endsWith('/apply')).length,0);
''')
