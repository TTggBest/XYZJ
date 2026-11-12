"""The actual upload form labels periods and sends independent multipart requests."""
from test_auth_frontend_contract import APP_FIXTURE,run_node


def test_dual_form_keeps_saved_names_separate_and_posts_periods():
    run_node(APP_FIXTURE+r'''
const uploaded=[];
const run={id:'run',mode:'periodic',input_snapshot:{studio_input_contract:'dual-window-v1'},materials:[
 {id:'old28',kind:'studio_zip',name:'old28.zip',studio_role:'recent_28d',period:{span_days:28,end:'2026-11-10'}},
 {id:'old7',kind:'studio_zip',name:'old7.zip',studio_role:'recent_7d',period:{span_days:7,end:'2026-11-10'}}]};
class FixtureFormData {
 constructor(form){this.data=new Map(form?Object.entries({studio_filter_scope:'videos only'}):[]);}
 append(k,v){this.data.set(k,v)}
 entries(){return this.data.entries()}
 get(k){return this.data.get(k)}
}
class Transfer {items={add:()=>{}};files=[];}
const page=start(process.argv[1],auth,async(path,options)=>{
 if(path==='/api/v3/analysis-runs/run')return new Response(JSON.stringify(run));
 if(path==='/api/v3/analysis-runs/run/materials'){
   uploaded.push({role:options.body.get('studio_role'),kind:options.body.get('kind'),file:options.body.get('file').name,scope:options.body.get('filter_scope')});
   return new Response(JSON.stringify(run));
 }
 if(path==='http://127.0.0.1:19733/prepare')return new Response('{"ready":true,"executor_protocol":15,"host_id":"d1","tenant_id":"t1"}');
 if(path==='/api/v3/analysis-runs/run/start')return new Response('{"detail":"fixture stops before live execution"}',{status:409});
 return defaultResponse(path);
},{FormData:FixtureFormData,DataTransfer:Transfer});
await settle(page);await clickAction(page,'edit-analysis-materials',{id:'run'});
const html=page.nodes.get('modalBody').innerHTML;
assert.match(html,/28天＋最近7天两份ZIP/);
assert.match(html,/data-studio-role="recent_7d"/);
assert.match(html,/data-studio-role="previous_7d"/);
assert.match(html,/截图保持28天/);
assert.doesNotMatch(html,/无需另传7天/);
const sections=html.split('<section');
assert(sections.find(x=>x.includes('analysis-material-recent_28d')).includes('old28.zip'));
assert(!sections.find(x=>x.includes('analysis-material-recent_28d')).includes('old7.zip'));
const inputs=['recent_7d','recent_28d'].map(role=>{
 const status={dataset:{savedNames:'[]'},classList:{toggle(){}},innerHTML:''};
 return {name:'studio_zip',dataset:{studioRole:role},files:[{name:role+'.zip'}],closest:()=>({querySelector:()=>status})};
});
const form={id:'channelAnalysisMaterialsForm',dataset:{runId:'run',dualWindow:'true'},matches:()=>false,
 elements:{studio_filter_scope:{value:'videos only'}},querySelectorAll:()=>inputs};
await page.document.emit('submit',{target:form});
assert.deepEqual(uploaded,[
 {role:'recent_7d',kind:'studio_zip',file:'recent_7d.zip',scope:'videos only'},
 {role:'recent_28d',kind:'studio_zip',file:'recent_28d.zip',scope:'videos only'}]);
''')
