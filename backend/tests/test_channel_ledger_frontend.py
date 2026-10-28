from test_auth_frontend_contract import run_node


BOOT = r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const calls=[];let synced=false;
const channels=[{channel_id:'c1',display_name:'法语频道',original_name:'法语频道',default_language:'fr',authorized_account_count:1},
 {channel_id:'c2',display_name:'英语频道',original_name:'英语频道',default_language:'en',authorized_account_count:0}];
const ledger={channel_id:'c1',channel_name:'法语频道',language:'fr',total:3,drama_count:2,page:1,pages:1,page_size:50,
 last_synced_at:null,sync_complete:false,inventory_basis:'制作完成且对应语言素材就绪',items:[
 {row_id:'v1',group_id:'d1',drama_title:'甲剧',drama_code:'DRM-ONE',youtube_video_id:'public00001',visibility:'public',is_public:true},
 {row_id:'v2',group_id:'d1',drama_title:'甲剧',drama_code:'DRM-ONE',youtube_video_id:'failed00001',visibility:'failed',failed:true,failure_message:'上传或处理失败',has_schedule:true,planned_at:'2026-11-01T18:00:00Z'},
 {row_id:'i2',group_id:'d2',drama_title:'乙剧',drama_code:'DRM-TWO',visibility:'not_uploaded'}]};
const page=start(process.argv[1],auth,async(path,options)=>{
 calls.push([path,options?.method||'GET']);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify({...principal,permissions:[...principal.permissions,'youtube.manage']}));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"builder"}');
 if(path==='/api/v3/channels/overview')return new Response(JSON.stringify(channels));
 if(path==='/api/v3/settings/youtube-oauth')return new Response('{"configured":true,"can_manage":true}');
 if(path.includes('/youtube-videos/sync')){synced=true;return new Response('{"fetched":3}');}
 if(path.includes('/drama-ledger')){
  const data=structuredClone(ledger);if(synced){data.sync_complete=true;data.last_synced_at='2026-10-28T12:00:00Z';}
  if(path.includes('visibility=failed'))data.items=data.items.filter(r=>r.failed);
  if(path.includes('/c2/')){data.channel_id='c2';data.channel_name='英语频道';data.items=[];}
  return new Response(JSON.stringify(data));
 }
 return new Response('[]');
});
page.document.querySelector=()=>null;
async function settle(){for(let i=0;i<6;i++)await page.tick();}
async function click(action,extra={}){await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?{dataset:{action,...extra},closest:()=>null}:null}});await settle();}
await settle();
await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?{dataset:{view:'channels'}}:null}});await settle();
"""


def test_channel_entry_opens_full_ledger_and_highlights_failed_upload_without_hiding_duplicates():
    run_node(BOOT + r"""
assert.match(page.nodes.get('viewRoot').innerHTML,/data-action="channel-ledger"/);
await click('channel-ledger',{id:'c1'});
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/剧名/);assert.match(html,/我们的ID/);assert.match(html,/公开范围/);
assert.match(html,/ledger-row-failed/);assert.match(html,/上传或处理失败/);
assert.match(html,/public00001/);assert.match(html,/failed00001/);assert.match(html,/乙剧/);
assert.match(html,/ledger-public-check/);assert.match(html,/同步尚未完整/);
assert.equal(page.nodes.get('drawer').classList.contains('is-open'),false);
assert.match(page.nodes.get('pageTitle').textContent,/法语频道/);
await click('back-ledger-channels');
assert.match(page.nodes.get('viewRoot').innerHTML,/频道清单/);
""")


def test_ledger_filters_switch_channel_and_sync_refresh_the_current_ledger():
    run_node(BOOT + r"""
await click('channel-ledger',{id:'c1'});
page.nodes.set('ledgerSearch',{value:'甲剧'});
page.nodes.set('ledgerVisibility',{value:'failed'});
page.nodes.set('ledgerScheduled',{value:'true'});
await click('apply-ledger-filters');
const request=calls.filter(([p])=>p.includes('/drama-ledger')).at(-1)[0];
assert.match(request,/visibility=failed/);assert.match(request,/scheduled=true/);assert.match(request,/query=/);
assert.doesNotMatch(page.nodes.get('viewRoot').innerHTML,/public00001/);
await click('sync-ledger-videos');assert.equal(synced,true);
assert.ok(calls.some(([p,m])=>p==='/api/v3/channels/c1/youtube-videos/sync'&&m==='POST'));
assert.match(page.nodes.get('viewRoot').innerHTML,/最近同步/);
await page.document.emit('change',{target:{id:'ledgerChannel',value:'c2',matches:()=>false}});await settle();
assert.match(page.nodes.get('pageTitle').textContent,/英语频道/);
assert.ok(calls.some(([p])=>p.startsWith('/api/v3/channels/c2/drama-ledger')));
""")
