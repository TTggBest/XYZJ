from test_auth_frontend_contract import run_node,APP_FIXTURE


def test_workspace_result_page_and_monitor_refresh_keep_each_channel_separate():
    run_node(APP_FIXTURE+r"""
const timers=new Map();let seq=0,completed=2;const reads=[];
const run=(id,name)=>({id,channel_id:id,mode:'periodic',status:'running',created_at:'2026-11-04T00:00:00Z',heartbeat_at:new Date().toISOString(),input_snapshot:{model:'test'},progress:{stage:'screenshots',completed_items:name==='A'?completed:5,total_items:11,elapsed_seconds:60,stage_elapsed_seconds:20}});
const page=start(process.argv[1],auth,async(path)=>{
 if(path.startsWith('/api/v3/channel-analysis/workspace')){
  reads.push(path);const view=new URL('http://fixture'+path).searchParams.get('view');
  const items=view==='progress' ? [{channel_id:'A',channel_name:'频道甲',run:run('A','A')},{channel_id:'B',channel_name:'频道乙',run:run('B','B')}] : [{channel_id:'A',channel_name:'频道甲',current:null,latest:null},{channel_id:'B',channel_name:'频道乙',current:null,latest:null}];
  return new Response(JSON.stringify({items,total:2,page:1,pages:1,stats:{running:2,queued:1,failed:0,worker_limit:10}}));
 }
 return defaultResponse(path);
},{setTimeout:(fn,ms)=>{const id=++seq;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
await settle(page);
await page.document.emit('click',{target:{closest:selector=>selector==='[data-view]'?{dataset:{view:'channelAnalysis'}}:null}});await settle(page);
let html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/频道甲/);assert.match(html,/频道乙/);assert.match(html,/分析结果/);assert.match(html,/分析进度/);
await clickAction(page,'analysis-workspace-tab',{tab:'progress'});
html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/已完成 2 \/ 11 张/);assert.match(html,/已完成 5 \/ 11 张/);assert.match(html.replace(/<[^>]*>/g,""),/运行中\s*2/);assert.match(html.replace(/<[^>]*>/g,""),/排队\s*1/);
const timer=[...timers.entries()].find(([id,t])=>t.ms===5000);assert(timer);timers.delete(timer[0]);completed=3;
await timer[1].fn();assert.match(page.nodes.get('viewRoot').innerHTML,/已完成 3 \/ 11 张/);
const next=[...timers.values()].find(t=>t.ms===5000);assert(next);
await switchCompany(page);reads.length=0;await next.fn();assert.equal(reads.length,0);
""")


def test_result_layout_deduplicates_current_version_without_hiding_a_new_result():
    run_node(APP_FIXTURE+r"""
const current={id:'applied',report_version:2,is_current:true,status:'applied',result:{available:true}};
const newer={id:'newer',report_version:null,is_current:false,status:'ready',result:{available:true}};
const page=start(process.argv[1],auth,async(path)=>{
 if(path.startsWith('/api/v3/channel-analysis/workspace'))return new Response(JSON.stringify({items:[
  {channel_id:'A',channel_name:'频道甲',current,latest:current},
  {channel_id:'B',channel_name:'频道乙',current:{...current,id:'other'},latest:newer}
 ],total:2,page:1,pages:1,stats:{running:0,queued:0,failed:0,worker_limit:10}}));
 return defaultResponse(path);
});
await settle(page);
await page.document.emit('click',{target:{closest:selector=>selector==='[data-view]'?{dataset:{view:'channelAnalysis'}}:null}});await settle(page);
const html=page.nodes.get('viewRoot').innerHTML;
assert.equal((html.match(/data-action="view-analysis-result" data-id="applied"/g)||[]).length,1);
assert.match(html,/与当前一致/);assert.match(html,/待应用结果/);
assert.match(html,/data-action="view-analysis-result" data-id="newer"/);
assert.match(html,/data-action="channel-detail-tab"[^>]*data-id="A"/);
assert.doesNotMatch(html,/<h2>|section-head|settings-content-head/);
assert.match(html,/analysis-workspace-controls/);
""")
