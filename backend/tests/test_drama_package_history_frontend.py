from test_auth_frontend_contract import run_node


def test_completed_drama_opens_its_packages_and_compares_across_dates_without_writes():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const historyUI=require(process.argv[1]+'/assets/drama-package-history.js');
const calls=[];
const records=[{package_id:'p1',channel_id:'c1',channel_name:'英语频道',language_name:'英语',production_date:'2026-10-01',version_number:1,status:'text_ready'},
 {package_id:'p2',channel_id:'c2',channel_name:'法语频道',language_name:'法语',production_date:'2026-11-01',version_number:1,status:'text_ready'}];
const detail=id=>({record:records.find(r=>r.package_id===id),outputs:{titles:[{id:'title-'+id,variant_number:1,generation_number:1,localized_title:'Title '+id,chinese_translation:'中文 '+id,core_phrase:'真实卖点 '+id}],
 covers:[{id:'cover-'+id,title_id:'title-'+id,aspect_ratio:'16:9',creative_prompt:'不同封面 '+id}],descriptions:[{localized_text:'说明 '+id}],community_posts:[]}});
const page=start(process.argv[1],auth,async(path,options={})=>{
 calls.push([path,options.method||'GET']);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path.startsWith('/api/v3/drama-production'))return new Response(JSON.stringify({items:[{drama_id:'d1',drama_number:1,drama_code:'DR1',chinese_title:'完整剧目',overall_status:'completed',progress_percent:100,package_count:2,package_channel_count:2}],page:1,total:1,pages:1,page_size:50}));
 if(path==='/api/v3/dramas/d1/packages')return new Response(JSON.stringify({drama_id:'d1',drama_name:'完整剧目',drama_code:'DR1',package_count:2,channel_count:2,items:records}));
 if(path.startsWith('/api/v3/dramas/d1/packages/'))return new Response(JSON.stringify(detail(path.split('/').at(-1))));
 return new Response('[]');
},{window:{ZhijuDramaPackages:historyUI}});
for(let i=0;i<4;i++)await page.tick();
async function click(action,id){const button={dataset:{action,id},closest:()=>null};await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});}
await click('completed-drama-packages');
assert.match(calls.find(([p])=>p.startsWith('/api/v3/drama-production'))[0],/overall_status=completed/);
assert.match(page.nodes.get('viewRoot').innerHTML,/2 个频道/);
assert.match(page.nodes.get('viewRoot').innerHTML,/查看运营包/);
await click('drama-package-history','d1');
assert.match(page.nodes.get('drawerBody').innerHTML,/英语频道/);assert.match(page.nodes.get('drawerBody').innerHTML,/法语频道/);
assert.equal(calls.filter(([p])=>p.startsWith('/api/v3/dramas/d1/packages/')).length,0);
await click('drama-package-open','p1');
assert.match(page.nodes.get('drawerBody').innerHTML,/Title p1/);assert.match(page.nodes.get('drawerBody').innerHTML,/不同封面 p1/);
await click('drama-package-back');
for(const id of ['p1','p2'])await page.document.emit('change',{target:{dataset:{dramaPackageSelect:id},checked:true,matches:()=>false,classList:{contains:()=>false}}});
await click('drama-package-compare');
const html=page.nodes.get('drawerBody').innerHTML;
assert.match(html,/Title p1/);assert.match(html,/Title p2/);assert.match(html,/中文 p2/);assert.match(html,/2026-10-01/);assert.match(html,/2026-11-01/);
assert.equal(calls.filter(([p])=>p.endsWith('/packages/p1')).length,1);
assert.ok(calls.every(([,method])=>method==='GET'));
""")


def test_read_only_renderer_keeps_latest_title_cover_pair_and_missing_images_honest():
    run_node(r"""
const ui=require(process.argv[1]+'/assets/drama-package-history.js');
const record={package_id:'p',channel_name:'<Channel>',version_number:2,status:'failed'};
const outputs={titles:[{id:'new',variant_number:1,localized_title:'New title',chinese_translation:'新标题'},
 {id:'old',variant_number:1,localized_title:'Old superseded title'}],covers:[
 {id:'old-cover',title_id:'old',aspect_ratio:'16:9',creative_prompt:'OLD COVER'},
 {id:'new-cover',title_id:'new',aspect_ratio:'16:9',creative_prompt:'New cover prompt',asset_id:'asset-id'}],descriptions:[],community_posts:[]};
let html=ui.renderDetails({drama_name:'Drama'},[{record,outputs}],x=>x);
assert.match(html,/New title/);assert.match(html,/New cover prompt/);assert.doesNotMatch(html,/Old superseded title|OLD COVER/);
assert.match(html,/&lt;Channel&gt;/);assert.match(html,/图片暂不可读取/);assert.match(html,/\/media-assets\/asset-id\/thumbnail/);
assert.doesNotMatch(html,/data-action="(?:v14|approve|copy|sync|generate)/);
html=ui.renderHistory({drama_name:'No packages',items:[],package_count:0,channel_count:0},new Set(),x=>x);
assert.match(html,/尚未生产运营包/);assert.doesNotMatch(html,/并排对比/);
""")


def test_history_request_failure_exits_loading_state_and_offers_retry():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/dramas/d/packages')return new Response('{"detail":"读取失败"}',{status:503});
 return new Response('[]');
},{window:{ZhijuDramaPackages:require(process.argv[1]+'/assets/drama-package-history.js')}});
for(let i=0;i<4;i++)await page.tick();
const button={dataset:{action:'drama-package-history',id:'d'},closest:()=>null};
await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
assert.match(page.nodes.get('drawerBody').innerHTML,/读取失败/);
assert.match(page.nodes.get('drawerBody').innerHTML,/重新读取/);
assert.doesNotMatch(page.nodes.get('drawerBody').innerHTML,/正在读取/);
""")


def test_closed_drawer_ignores_late_history_response():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
let resolve;
const pending=new Promise(done=>{resolve=done});
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/dramas/d/packages')return pending;
 return new Response('[]');
},{window:{ZhijuDramaPackages:require(process.argv[1]+'/assets/drama-package-history.js')}});
for(let i=0;i<4;i++)await page.tick();
const button={dataset:{action:'drama-package-history',id:'d'},closest:()=>null};
const click=page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
await page.tick();
await page.document.emit('click',{target:{closest:s=>s==='[data-close-drawer]'?{}:null}});
resolve(new Response(JSON.stringify({drama_id:'d',drama_name:'Late data',items:[],channel_count:0,package_count:0})));
await click;
assert.equal(page.nodes.get('drawerBackdrop').hidden,true);
assert.doesNotMatch(page.nodes.get('drawerBody').innerHTML,/Late data/);
""")
