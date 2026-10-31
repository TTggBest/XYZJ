from test_auth_frontend_contract import run_node


def test_schedule_list_does_not_wait_for_unused_drama_selector():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
const user={...principal,permissions:[...principal.permissions,'schedule.read','schedule.manage','drama.read']};
const page=start(process.argv[1],auth,async(path)=>{
 requests.push(path);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(user));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"deployment":"cloud","device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"测试频道"}]');
 if(path==='/api/v3/schedules/eligible-dramas')return new Promise(()=>{});
 return new Response('[]');
});
for(let i=0;i<8;i++)await page.tick();
const nav={dataset:{view:'schedules'}};
const click=page.document.emit('click',{target:{closest:s=>s==='[data-view]'?nav:null}});
for(let i=0;i<8;i++)await page.tick();
assert.ok(requests.some(p=>p.startsWith('/api/v3/schedules/overview?')),'排期列表被新建排期的剧目选择数据阻塞');
assert.ok(!requests.includes('/api/v3/schedules/eligible-dramas'),'只在新建排期时加载剧目');
await click;
""")
