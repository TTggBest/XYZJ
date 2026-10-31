from test_auth_frontend_contract import run_node


def test_workorders_show_each_workflows_actual_six_or_eight_nodes():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const oldTypes=['search','title','cover','description','community','merge'];
const newTypes=['search','title','cover_scene','cover','description','community_scene','community','merge'];
const nodes=types=>Object.fromEntries(types.map(type=>[type,{status:type==='cover_scene'?'running':'completed'}]));
const tasks=[oldTypes,newTypes].map((types,i)=>({task_id:'t'+i,work_order_id:'w'+i,
 chinese_title:'drama'+i,task_status:'processing',execution_status:'running',
 progress_percent:i?25:33,nodes:nodes(types)}));
const page=start(process.argv[1],auth,async path=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false}');
 if(path.includes('/workflow-versions'))return new Response('{"versions":[]}');
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify(tasks));
 return new Response('[]');
});
for(let i=0;i<5;i++)await page.tick();
const b={dataset:{action:'go-workorders'},closest:()=>null};
await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?b:null}});
const html=page.nodes.get('viewRoot').innerHTML;
const strips=[...html.matchAll(/<div class="node-strip"[^>]*>([\s\S]*?)<\/div>/g)];
assert.equal(strips.length,2);
assert.equal((strips[0][1].match(/class="node-dot/g)||[]).length,6);
assert.equal((strips[1][1].match(/class="node-dot/g)||[]).length,8);
assert.match(strips[1][1],/is-active" title="封面场景规划/);
assert(strips[1][1].indexOf('标题')<strips[1][1].indexOf('封面场景规划'));
assert(strips[1][1].indexOf('社群场景规划')<strips[1][1].indexOf('社群：'));
''')
