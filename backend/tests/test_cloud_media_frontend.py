import pytest

from test_auth_frontend_contract import run_node


@pytest.mark.parametrize("deployment", ["cloud", "local"])
def test_package_previews_are_small_and_cloud_click_does_not_reveal_server_folder(deployment):
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const calls=[],opened=[];
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
 if(path.endsWith('/reveal'))return new Response('{"folder":"/fixture"}');
 return new Response('[]');
},{windowOpen:(...args)=>opened.push(args)});
for(let i=0;i<6;i++)await page.tick();
await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?{dataset:{view:'packages'}}:null}});
for(let i=0;i<4;i++)await page.tick();
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/北京时间[^<]*2026\/10\/27[^<]*01:00/);
assert.match(html,/当地时间[^<]*2026\/10\/26[^<]*13:00/);
assert.match(html,/北京时间[^<]*2026\/10\/27[^<]*03:00/);
assert.doesNotMatch(html,/GMT|UTC|America\/New_York/);
assert.match(html,/src="\/api\/v3\/media-assets\/asset-1\/thumbnail"/);
assert.doesNotMatch(html,/<img[^>]*src="[^"]*\/content"/);
assert.match(html,DEPLOYMENT==='cloud'?/下载原图/:/打开文件夹/);
const button={dataset:{action:'reveal-media-asset',id:'asset-1'},closest:()=>null};
await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
for(let i=0;i<2;i++)await page.tick();
if(DEPLOYMENT==='cloud'){
 assert.equal(calls.filter(([p])=>p.endsWith('/reveal')).length,0);
 assert.deepEqual(opened,[['/api/v3/media-assets/asset-1/content?download=true','_blank','noopener,noreferrer']]);
}else{
 assert.equal(opened.length,0);
 assert.equal(calls.filter(([p])=>p.endsWith('/reveal')).length,1);
}
'''.replace("DEPLOYMENT", repr(deployment)))
