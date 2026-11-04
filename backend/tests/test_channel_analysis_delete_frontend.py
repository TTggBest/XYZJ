from test_auth_frontend_contract import run_node,APP_FIXTURE


def test_delete_requires_confirmation_and_removes_only_abandoned_card():
    run_node(APP_FIXTURE+r"""
let confirmed=false,deleted=false;const mutations=[];
const rows=()=>[
 ...(!deleted?[{id:'failed',status:'failed'}]:[]),{id:'cancelled',status:'cancelled'}, {id:'applied',status:'applied'}
].map(r=>({...r,mode:'periodic',phase:'analysis',created_at:'2026-11-04T00:00:00Z',input_snapshot:{model:'test'},materials:[],mirror_status:'completed',result:r.status==='applied'?{available:true}:null}));
const page=start(process.argv[1],auth,async(path,options={})=>{
 if(options.method==='DELETE'){mutations.push(path);deleted=true;return new Response('{"status":"deleted"}');}
 if(path==='/api/v3/channels/c')return new Response(JSON.stringify({channel:{id:'c',original_name:'Test'},profile:null,keywords:[],pinned_comment_templates:[],playlists:[],branding_assets:[],drama_types:[],relevant_skills:[]}));
 if(path.startsWith('/api/v3/channels/c/analysis-history'))return new Response(JSON.stringify({items:rows(),current:null,total:rows().length,page:1,pages:1}));
 return defaultResponse(path);
},{window:{confirm:()=>confirmed}});
await settle(page);await clickAction(page,'channel-detail-tab',{id:'c',channelDetailTab:'analysis'});
let html=page.nodes.get('drawerBody').innerHTML;
assert.match(html,/data-action="delete-channel-analysis" data-id="failed"/);
assert.match(html,/data-action="delete-channel-analysis" data-id="cancelled"/);
assert.doesNotMatch(html,/data-action="delete-channel-analysis" data-id="applied"/);
await clickAction(page,'delete-channel-analysis',{id:'failed'});assert.equal(mutations.length,0);
confirmed=true;await clickAction(page,'delete-channel-analysis',{id:'failed'});
assert.deepEqual(mutations,['/api/v3/analysis-runs/failed']);
html=page.nodes.get('drawerBody').innerHTML;
assert.doesNotMatch(html,/data-id="failed"/);assert.match(html,/data-id="cancelled"/);assert.match(html,/data-id="applied"/);
""")
