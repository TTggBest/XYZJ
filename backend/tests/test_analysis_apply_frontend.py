import pytest
from test_auth_frontend_contract import run_node,APP_FIXTURE


@pytest.mark.parametrize('failure',[False,True])
def test_apply_is_cloud_only_with_immediate_feedback_and_no_large_task_read(failure):
    run_node(APP_FIXTURE+f"const failure={str(failure).lower()};"+r"""
let release,applied=false;
const requests=[];
const run={id:'run',channel_id:'c',status:'ready',mode:'periodic',input_snapshot:{model:'test'},result:{available:true},materials:[]};
const page=start(process.argv[1],auth,async(path)=>{
 requests.push(path);
 if(path==='/api/v3/channels/c')return new Response(JSON.stringify({channel:{id:'c',original_name:'Test'},profile:null,keywords:[],pinned_comment_templates:[],playlists:[],branding_assets:[],drama_types:[],relevant_skills:[]}));
 if(path.startsWith('/api/v3/channels/c/analysis-history'))return new Response(JSON.stringify({items:[run],current:applied?{...run,status:'applied',report_version:1}:null,total:1,page:1,pages:1}));
 if(path==='/api/v3/analysis-runs/run/apply')return new Promise(resolve=>release=()=>{
  applied=!failure;
  resolve(new Response(JSON.stringify(failure?{detail:'应用保存失败'}:{id:'run',status:'applied',mirror_status:'pending'}),{status:failure?503:200}));
 });
 return defaultResponse(path);
});
await settle(page);await clickAction(page,'channel-detail-tab',{id:'c',channelDetailTab:'analysis'});
requests.length=0;
const button={dataset:{action:'apply-channel-analysis',id:'run'},textContent:'应用此版本',disabled:false,isConnected:true,closest:()=>null,querySelector:()=>null};
const click=()=>page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
const pending=click();await settle(page);
assert.equal(button.disabled,true);assert.equal(button.textContent,'正在应用版本…');
assert.deepEqual(requests,['/api/v3/analysis-runs/run/apply']);
await click();assert.equal(requests.length,1);
release();await pending;
assert.equal(button.disabled,false);assert.equal(button.textContent,'应用此版本');
assert(!requests.some(p=>p.includes('executor-session')||p.includes('127.0.0.1')||p==='/api/v3/analysis-runs/run'));
if(failure){assert.doesNotMatch(page.nodes.get('drawerBody').innerHTML,/当前生产使用：报告 v1/);}
else{assert.match(page.nodes.get('drawerBody').innerHTML,/当前生产使用：报告 v1/);}
""")
