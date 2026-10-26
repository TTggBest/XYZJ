import pytest

from test_auth_frontend_contract import run_node


@pytest.mark.parametrize("deployment", ["cloud", "local"])
def test_image_settings_use_tenant_path_and_only_offer_supported_icon_upload(deployment):
    run_node(r'''
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify({...superUser,permissions:[...superUser.permissions,'platform.environment.manage']}));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response(JSON.stringify({enabled:false,device_role:'builder',deployment:DEPLOYMENT}));
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/settings/image-workspace')return new Response('null');
 if(path==='/api/v3/settings/app-icon')return new Response('{"preview_url":"/icon.png","source_type":"default"}');
 return new Response('[]');
});
for(let i=0;i<8;i++)await page.tick();
await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?{dataset:{view:'settings'}}:null}});
for(let i=0;i<4;i++)await page.tick();
async function tab(name){
 await page.document.emit('click',{target:{closest:s=>s==='[data-settings-tab]'?{dataset:{settingsTab:name}}:null}});
 for(let i=0;i<4;i++)await page.tick();
}
await tab('images');
assert.match(page.nodes.get('viewRoot').innerHTML,/value="tenants\/t1\/images"/);
assert.doesNotMatch(page.nodes.get('viewRoot').innerHTML,/绝对路径只用于/);
await tab('packages');
const html=page.nodes.get('viewRoot').innerHTML;
if(DEPLOYMENT==='cloud'){
 assert.doesNotMatch(html,/id="appIconForm"|data-action="restore-default-icon"/);
 assert.match(html,/云端不支持.*桌面图标/);
}else{
 assert.match(html,/id="appIconForm"/);
 assert.match(html,/data-action="restore-default-icon"/);
}
'''.replace("DEPLOYMENT", repr(deployment)))
