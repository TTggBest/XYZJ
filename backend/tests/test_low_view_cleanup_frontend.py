from test_auth_frontend_contract import run_node


def test_channel_cleanup_fetches_preview_and_only_executes_on_explicit_button():
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const user={...principal,permissions:[...principal.permissions,'channel.manage']};
const requests=[];
const preview={channel_id:'c1',channel_name:'测试频道',fetched_at:'2026-11-11T12:00:00Z',fetched_count:12,
 candidates:[{video_id:'local-1',youtube_video_id:'video000000',title:'<script>禁止作为HTML</script>',age_days:5,
 views:99,baseline_views:1000,threshold_views:200,sample_count:5}],pending_cleanup:[],skipped:[]};
const page=start(process.argv[1],auth,async(path,options={})=>{
 requests.push([path,options]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(user));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"deployment":"cloud","device_role":"worker"}');
 if(path==='/api/v3/channels/c1/low-view-cleanup/preview')return new Response(JSON.stringify(preview));
 if(path==='/api/v3/channels/c1/low-view-cleanup/execute')return new Response(JSON.stringify({deleted_count:1,cleaned_count:1,
 completed:[{youtube_video_id:'video000000'}],failed:[],skipped:[]}));
 return new Response('[]');
});
for(let i=0;i<8;i++)await page.tick();
function button(action){const b={dataset:{action,id:'c1'},isConnected:true};b.closest=s=>s==='[data-action]'?b:null;return b;}
await page.document.emit('click',{target:button('low-view-cleanup')});
assert.equal(requests.filter(([p])=>p.endsWith('/execute')).length,0);
const body=page.nodes.get('modalBody').innerHTML;
assert.ok(body.includes('低于 200'));
assert.ok(body.includes('删除 1 个视频并清理记录'));
assert.ok(body.includes('&lt;script&gt;'));
await page.document.emit('click',{target:button('execute-low-view-cleanup')});
const executions=requests.filter(([p])=>p.endsWith('/execute'));
assert.equal(executions.length,1);
assert.deepEqual(JSON.parse(executions[0][1].body),{video_ids:['local-1']});
assert.ok(page.nodes.get('modalBody').innerHTML.includes('完成关联清理 1 条'));
await page.document.emit('click',{target:button('execute-low-view-cleanup')});
assert.equal(requests.filter(([p])=>p.endsWith('/execute')).length,1);
''')
