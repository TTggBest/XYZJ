from test_auth_frontend_contract import run_node

BOOT = r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
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
 if(path.endsWith('/v14-runs')&&opts.method==='POST'){
  if(createError)return new Response('{"detail":"请先配置 V14 执行主机、模型和规则"}',{status:409});
  run={run_id:'run-a',status:'queued',host_id:'device-a',model:'selected-model',attempts:[]};
  return new Response(JSON.stringify(run));
 }
 return new Response('[]');
});
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
