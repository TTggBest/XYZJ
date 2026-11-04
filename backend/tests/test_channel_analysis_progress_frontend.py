from test_auth_frontend_contract import run_node, APP_FIXTURE


def test_analysis_progress_refreshes_only_cards_and_stops_after_company_switch():
    run_node(APP_FIXTURE + r"""
const timers=new Map();let seq=0,count=2;
const run=()=>({id:'run',mode:'periodic',status:'running',phase:'analysis',created_at:'2026-11-04T07:00:00Z',heartbeat_at:new Date().toISOString(),input_snapshot:{model:'test'},materials:Array(12).fill({}),mirror_status:'pending',progress:{stage:'screenshots',completed_items:count,total_items:11,current_item:'Audience.png',elapsed_seconds:120,stage_elapsed_seconds:30}});
const reads=[];
const page=start(process.argv[1],auth,async(path)=>{
 reads.push(path);
 if(path==='/api/v3/channels/c')return new Response(JSON.stringify({channel:{id:'c',original_name:'Test'},profile:null,keywords:[],pinned_comment_templates:[],playlists:[],branding_assets:[],drama_types:[],relevant_skills:[]}));
 if(path==='/api/v3/channels/c/analysis-runs')return new Response(JSON.stringify([run()]));
 return defaultResponse(path);
},{setTimeout:(fn,ms)=>{const id=++seq;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
await settle(page);
await clickAction(page,'channel-detail-tab',{id:'c',channelDetailTab:'analysis'});
assert.match(page.nodes.get('drawerBody').innerHTML,/已完成 2 \/ 11 张/);
assert.match(page.nodes.get('drawerBody').innerHTML,/执行器在线/);
assert.match(page.nodes.get('drawerBody').innerHTML,/当前步骤 0分30秒/);
// The minimal DOM boundary does not parse inserted HTML; provide the actual card container.
const cards={innerHTML:''};page.nodes.set('channelAnalysisRuns',cards);
let timer=[...timers.entries()].find(([id,t])=>t.ms===5000);assert(timer);
timers.delete(timer[0]);count=3;reads.length=0;await timer[1].fn();
assert.match(cards.innerHTML,/已完成 3 \/ 11 张/);
assert.deepEqual(reads,['/api/v3/channels/c/analysis-runs']);
timer=[...timers.entries()].find(([id,t])=>t.ms===5000);assert(timer);
await switchCompany(page);reads.length=0;await timer[1].fn();
assert.equal(reads.includes('/api/v3/channels/c/analysis-runs'),false);
""")
