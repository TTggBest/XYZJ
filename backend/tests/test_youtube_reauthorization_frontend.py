import json
import pytest
from test_auth_frontend_contract import run_node


@pytest.mark.parametrize("failure,visible", [
    ({"code": "youtube_reauthorization_required", "channel_id": "c1", "message": "YouTube授权已失效"}, True),
    ("无法连接YouTube API", False),
    ("YouTube API请求失败：HTTP 403", False),
])
def test_reauthorization_only_appears_after_auth_failure_and_clears_on_success(failure, visible):
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[], popup={location:{},focus(){},close(){}};
const user={...principal,permissions:[...principal.permissions,'channel.manage']};
const page=start(process.argv[1],auth,async(path,options)=>{
 requests.push(path);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(user));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"deployment":"cloud","device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"测试频道"}]');
 if(path.endsWith('/youtube-videos/sync'))return new Response(JSON.stringify({detail:FAILURE}),{status:409});
 if(path.endsWith('/youtube-authorization/start'))return new Response('{"authorization_url":"https://accounts.google.com/test"}');
 return new Response('[]');
},{windowOpen:()=>popup});
for(let i=0;i<5;i++)await page.tick();
const notice=page.nodes.get('youtubeReauthorizationNotice');
assert.equal(notice.hidden,true);
async function click(action,id){
 const button={dataset:{action,id},closest:()=>null};
 await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
}
await click('sync-youtube-videos','c1');
assert.equal(notice.hidden,!VISIBLE);
assert.ok(auth.current(),'YouTube errors must not log out the web session');
if(VISIBLE){
 assert.match(notice.innerHTML,/重新授权/);
 assert.match(notice.innerHTML,/data-id="c1"/);
 await click('authorize-youtube-channel','c1');
 assert.ok(requests.includes('/api/v3/channels/c1/youtube-authorization/start'));
 assert.equal(popup.location.href,'https://accounts.google.com/test');
 await page.window.emit('message',{origin:'http://fixture',data:{type:'youtube-auth-failed',channel_id:'c1'}});
 assert.equal(notice.hidden,false,'cancelled authorization must keep recovery available');
 await page.window.emit('message',{origin:'http://fixture',data:{type:'youtube-auth-complete',channel_id:'other-channel'}});
 assert.equal(notice.hidden,false,'a different channel must not clear this failure');
 await page.window.emit('message',{origin:'http://fixture',data:{type:'youtube-auth-complete',channel_id:'c1'}});
 assert.equal(notice.hidden,true);
}
""".replace("FAILURE", json.dumps(failure, ensure_ascii=False)).replace("VISIBLE", str(visible).lower()))
