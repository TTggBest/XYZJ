from pathlib import Path
from test_auth_frontend_contract import run_node,APP_FIXTURE


def test_bound_version_stays_visible_across_history_pages_and_docs_are_loaded_on_demand():
    run_node(APP_FIXTURE+r"""
const bound={id:'current',is_current:true,report_version:2,skill_label:"正式分析",skill_revision:7,status:'applied',mode:'periodic',created_at:'2026-11-04T00:00:00Z',input_snapshot:{model:'test'},materials:[],mirror_status:'completed',result:{available:true}};
const old={...bound,id:'old',is_current:false,report_version:1,skill_revision:3,status:'superseded'};
const pathsRead=[];
const page=start(process.argv[1],auth,async(path)=>{
 pathsRead.push(path);
 if(path==='/api/v3/channels/c')return new Response(JSON.stringify({channel:{id:'c',original_name:'Test'},profile:null,keywords:[],pinned_comment_templates:[],playlists:[],branding_assets:[],drama_types:[],relevant_skills:[]}));
 if(path.startsWith('/api/v3/channels/c/analysis-history')){
  const n=Number(new URL('http://fixture'+path).searchParams.get('page'));
  return new Response(JSON.stringify({items:n===1?[bound]:[old],current:bound,total:35,page:n,pages:4}));
 }
 if(path==='/api/v3/analysis-runs/old')return new Response(JSON.stringify({...old,result:{profile:'# 历史长期档案\n\n原始依据 <script>bad()</script>',diagnosis:'## 当前诊断\n\n历史诊断正文',generation_spec:'## 生成规范\n\n历史规范'}}));
 return defaultResponse(path);
});
await settle(page);await clickAction(page,'channel-detail-tab',{id:'c',channelDetailTab:'analysis'});
let html=page.nodes.get('drawerBody').innerHTML;
assert.match(html,/当前生产使用：报告 v2/);assert.match(html,/分析 Skill：正式分析 · 修订 7/);
assert.doesNotMatch(html,/同步本地文件|重试交付文件|本地归档/);
assert.match(html,/共 35 条 · 第 1 \/ 4 页/);assert.doesNotMatch(html,/暂无频道日数据|题材与关键词|报告摘要/);
assert.match(html,/channel-hub-fixed/);assert.match(html,/analysis-toolbar/);
assert(!pathsRead.some(path=>path.includes('analysis-reports')));
await clickAction(page,'analysis-history-page',{id:'c',page:'2'});
html=page.nodes.get('drawerBody').innerHTML;
assert.match(html,/当前生产使用：报告 v2/);assert.match(html,/报告 v1/);assert.match(html,/已被新版替代/);
assert.match(html,/第 2 \/ 4 页/);assert.doesNotMatch(html,/分析完成，待应用/);
assert(!pathsRead.includes('/api/v3/analysis-runs/old'));
await clickAction(page,'view-analysis-result',{id:'old'});
html=page.nodes.get('modalBody').innerHTML;
assert.match(html,/<h2>历史长期档案<\/h2>/);assert.match(html,/&lt;script&gt;bad\(\)&lt;\/script&gt;/);
assert.doesNotMatch(html,/<script>|<textarea|hub-columns/);
await clickAction(page,'analysis-document-tab',{key:'diagnosis'});
html=page.nodes.get('modalBody').innerHTML;
assert.match(html,/历史诊断正文/);assert.doesNotMatch(html,/原始依据/);
""")


def test_analysis_fixed_controls_are_siblings_of_only_vertical_scroller():
    root=Path(__file__).resolve().parents[2]
    css=(root/'assets/styles.css').read_text()
    assert '.drawer-body:has(.channel-hub-analysis) { overflow: hidden;' in css
    assert '.channel-hub-analysis .channel-hub-fixed { flex: 0 0 auto;' in css
    assert '.channel-hub-analysis .channel-hub-panel { flex: 1; min-height: 0; overflow-y: auto;' in css
    assert '.modal:has(.analysis-reader)' in css


def test_slow_previous_page_cannot_replace_latest_requested_page():
    run_node(APP_FIXTURE+r"""
let hold,release,readLegacy=false;
const response=n=>new Response(JSON.stringify({items:[],current:null,total:35,page:n,pages:4}));
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/channels/c')return new Response(JSON.stringify({channel:{id:'c',original_name:'Test'},profile:null,keywords:[],pinned_comment_templates:[],playlists:[],branding_assets:[],drama_types:[],relevant_skills:[]}));
 if(path.includes('analysis-history')){const n=Number(new URL('http://fixture'+path).searchParams.get('page'));if(n===2){hold=new Promise(r=>release=r);return hold;}return response(n);}
 return defaultResponse(path);
});
await settle(page);await clickAction(page,'channel-detail-tab',{id:'c',channelDetailTab:'analysis'});
const old=clickAction(page,'analysis-history-page',{id:'c',page:'2'});await settle(page);
await clickAction(page,'analysis-history-page',{id:'c',page:'3'});
release(response(2));await old;
assert.match(page.nodes.get('drawerBody').innerHTML,/第 3 \/ 4 页/);
""")


def test_manual_history_report_remains_readable_without_analysis_task():
    run_node(APP_FIXTURE+r"""
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/channels/c')return new Response(JSON.stringify({channel:{id:'c',original_name:'Test'},profile:null,keywords:[],pinned_comment_templates:[],playlists:[],branding_assets:[],drama_types:[],relevant_skills:[]}));
 if(path.includes('analysis-history'))return new Response(JSON.stringify({items:[{id:'manual',channel_id:'c',kind:'report',status:'legacy_report',mode:'manual',report_version:1,created_at:'2026-11-01T00:00:00Z',input_snapshot:{model:'manual'},materials:[],result:{available:true}}],current:null,total:1,page:1,pages:1}));
 if(path==='/api/v3/channels/c/analysis-reports/manual')return new Response(JSON.stringify({id:'manual',version_number:1,created_at:'2026-11-01T00:00:00Z',summary:'# 人工报告正文',recommendations:'人工建议',topic_scores:[{topic:'保留的结构化结论'}]}));
 return defaultResponse(path);
});
await settle(page);await clickAction(page,'channel-detail-tab',{id:'c',channelDetailTab:'analysis'});
assert.match(page.nodes.get('drawerBody').innerHTML,/查看历史报告/);
await clickAction(page,'view-legacy-analysis-report',{id:'manual',channelId:'c'});
assert.match(page.nodes.get('modalBody').innerHTML,/人工报告正文/);
await clickAction(page,'analysis-document-tab',{key:'legacy_details'});
assert.match(page.nodes.get('modalBody').innerHTML,/保留的结构化结论/);
assert.doesNotMatch(page.nodes.get('modalBody').innerHTML,/下载事实快照/);
""")


def test_creating_analysis_from_old_page_returns_to_first_page():
    run_node(APP_FIXTURE+r"""
let created=false;const historyReads=[];
const fresh={id:'fresh',mode:'periodic',status:'draft',created_at:'2026-11-04T00:00:00Z',input_snapshot:{model:'test'},materials:[],mirror_status:'pending'};
class FixtureFormData {constructor(form){this.data=form.data;} entries(){return Object.entries(this.data)[Symbol.iterator]();}}
const page=start(process.argv[1],auth,async(path,options={})=>{
 if(path==='/api/v3/channels/c')return new Response(JSON.stringify({channel:{id:'c',original_name:'Test'},profile:null,keywords:[],pinned_comment_templates:[],playlists:[],branding_assets:[],drama_types:[],relevant_skills:[]}));
 if(path==='/api/v3/channels/c/analysis-runs' && options.method==='POST'){created=true;return new Response(JSON.stringify(fresh));}
 if(path.includes('analysis-history')){const n=Number(new URL('http://fixture'+path).searchParams.get('page'));historyReads.push(n);return new Response(JSON.stringify({items:created&&n===1?[fresh]:[],current:null,total:35,page:n,pages:4}));}
 return defaultResponse(path);
},{FormData:FixtureFormData});
await settle(page);await clickAction(page,'channel-detail-tab',{id:'c',channelDetailTab:'analysis'});
await clickAction(page,'analysis-history-page',{id:'c',page:'3'});
await page.document.emit('submit',{target:{id:'channelAnalysisCreateForm',dataset:{channelId:'c'},data:{mode:'periodic',positioning:''},elements:{posts_not_applicable:{checked:false},ab_not_applicable:{checked:false}}}});
assert.equal(historyReads.at(-1),1);assert.match(page.nodes.get('drawerBody').innerHTML,/data-id="fresh"/);
""")
