import pytest

from test_auth_frontend_contract import run_node


@pytest.mark.parametrize("deployment", ["cloud", "local"])
def test_package_previews_are_small_and_cloud_click_does_not_reveal_server_folder(deployment):
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const calls=[],opened=[];let downloadClicks=0;
const item={package_id:'p1',work_order_id:'w1',channel_id:'c1',chinese_title:'剧目',status:'review_pending',
 titles:[{id:'t1',variant_number:1,localized_title:'title'}],
 covers:[{title_id:'t1',aspect_ratio:'16:9',asset_id:'asset-1'}],
 production_date:'2026-10-27',channel_timezone:'America/New_York',planned_utc_time:'2026-10-26T17:00:00Z',
 media_assets:[{id:'asset-1'}],community_posts:[{id:'post-1',sequence_number:1,planned_utc_time:'2026-10-26T19:00:00Z'}],playlists:[]};
const page=start(process.argv[1],auth,async(path,opts={})=>{
 calls.push([path,opts]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(superUser));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response(JSON.stringify({enabled:false,device_role:'builder',deployment:DEPLOYMENT}));
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path.startsWith('/api/v3/packages/operations-overview'))return new Response(JSON.stringify([item]));
 if(path.includes('/content?download=true'))return new Response(new Uint8Array([1,2,3]),{headers:{'Content-Type':'image/png','Content-Disposition':'attachment; filename="cover.png"'}});
 if(path.endsWith('/download-complete')){assert.equal(downloadClicks,1);return new Response(JSON.stringify({asset_id:'asset-1',downloaded_at:'2026-11-01T10:00:00Z'}));}
 if(path.endsWith('/reveal'))return new Response('{"folder":"/fixture"}');
 return new Response('[]');
},{windowOpen:(...args)=>opened.push(args),URL:{createObjectURL:()=>"blob:fixture",revokeObjectURL(){}}});
const originalCreate=page.document.createElement;page.document.createElement=type=>({...originalCreate(type),click(){if(type==='a')downloadClicks++;}});
for(let i=0;i<6;i++)await page.tick();
await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?{dataset:{view:'packages'}}:null}});
for(let i=0;i<4;i++)await page.tick();
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/class="schedule-zone schedule-zone-beijing">北京时间 2026\/10\/27 <strong class="schedule-clock">01:00<\/strong>/);
assert.match(html,/class="schedule-zone schedule-zone-local">当地时间 2026\/10\/26 <strong class="schedule-clock">13:00<\/strong>/);
assert.match(html,/class="schedule-zone schedule-zone-beijing">北京时间 2026\/10\/27 <strong class="schedule-clock">03:00<\/strong>/);
assert.match(html,/class="schedule-zone schedule-zone-local">当地时间 2026\/10\/26 <strong class="schedule-clock">15:00<\/strong>/);
assert.doesNotMatch(html,/GMT|UTC|America\/New_York/);
assert.match(html,/src="\/api\/v3\/media-assets\/asset-1\/thumbnail"/);
assert.doesNotMatch(html,/<img[^>]*src="[^"]*\/content"/);
assert.match(html,DEPLOYMENT==='cloud'?/下载原图/:/打开文件夹/);
const button={dataset:{action:'reveal-media-asset',id:'asset-1'},closest:()=>null};
await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
for(let i=0;i<2;i++)await page.tick();
if(DEPLOYMENT==='cloud'){
 assert.equal(calls.filter(([p])=>p.endsWith('/reveal')).length,0);
 assert.equal(opened.length,0);assert.equal(downloadClicks,1);
 assert.ok(calls.some(([p])=>p.endsWith('/download-complete')));
}else{
 assert.equal(opened.length,0);
 assert.equal(calls.filter(([p])=>p.endsWith('/reveal')).length,1);
}
const detailButton={dataset:{action:'package-page-detail',id:'p1'},closest:()=>null};
await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?detailButton:null}});
for(let i=0;i<2;i++)await page.tick();
const detailHtml=page.nodes.get('viewRoot').innerHTML;
assert.match(detailHtml,/class="schedule-zone schedule-zone-beijing">北京时间 2026\/10\/27 <strong class="schedule-clock">01:00<\/strong>/);
assert.match(detailHtml,/class="schedule-zone schedule-zone-local">当地时间 2026\/10\/26 <strong class="schedule-clock">13:00<\/strong>/);
'''.replace("DEPLOYMENT", repr(deployment)))
