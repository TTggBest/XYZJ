from test_auth_frontend_contract import run_node


def test_node_filters_render_and_submit_independently_of_overall_status():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const paths=[];
const page=start(process.argv[1],auth,async(path)=>{
  paths.push(path);
  if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
  if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
  if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
  if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
  if(path.startsWith('/api/v3/drama-production'))return new Response('{"items":[],"total":0,"page":1,"pages":0,"page_size":50}');
  return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(action){
  const button={dataset:{action},closest:()=>null};
  await page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
}
await click('go-drama-progress');
let html=page.nodes.get('viewRoot').innerHTML;
assert.match(html, /制作节点/); assert.match(html, /节点状态/); assert.doesNotMatch(html, /当前节点/);
assert.equal((html.match(/已完成＋进行中/g)||[]).length,2);
for(const [id,value] of Object.entries({dramaProgressNode:'tts',dramaProgressNodeStatus:'completed',dramaProgressStatus:''})){
  page.nodes.set(id,{value});
}
await click('apply-drama-progress-filters');
let url=new URL(paths.filter(p=>p.startsWith('/api/v3/drama-production')).at(-1),'http://fixture');
assert.equal(url.searchParams.get('node'),'tts');
assert.equal(url.searchParams.get('node_status'),'completed');
assert.equal(url.searchParams.has('overall_status'),false);
assert.equal(url.searchParams.has('current_node'),false);
assert.match(page.nodes.get('viewRoot').innerHTML, /value="completed" selected/);
page.nodes.get('dramaProgressNodeStatus').value='completed_or_in_progress';
page.nodes.get('dramaProgressStatus').value='completed_or_in_progress';
await click('apply-drama-progress-filters');
url=new URL(paths.filter(p=>p.startsWith('/api/v3/drama-production')).at(-1),'http://fixture');
assert.equal(url.searchParams.get('node_status'),'completed_or_in_progress');
assert.equal(url.searchParams.get('overall_status'),'completed_or_in_progress');
// A node status without a selected node must not silently run an unfiltered query.
const count=paths.length;
page.nodes.get('dramaProgressNode').value='';
await click('apply-drama-progress-filters');
assert.equal(paths.length,count);
""")
