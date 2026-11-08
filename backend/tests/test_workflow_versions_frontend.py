from test_auth_frontend_contract import run_node
from test_v14_frontend import BOOT

REGISTRY_BOOT = BOOT.replace('versions:[', "versions:[{id:'v15',label:'V15',revision:1,status:'published'},")


def test_production_picker_sends_selected_skill_version():
    run_node(REGISTRY_BOOT + r"""
await click('work-detail','work-a');
assert.match(page.nodes.get('drawerBody').innerHTML,/本次生产流程版本/);
assert.match(page.nodes.get('drawerBody').innerHTML,/V15/);
await page.document.emit('change',{target:{id:'',value:'v15',matches:s=>s==='[data-workflow-selector]'}});
await click('v14-start','work-a');
const request=requests.find(([p,o])=>p.endsWith('/v14-runs')&&o.method==='POST');
assert.equal(JSON.parse(request[1].body).workflow_version_id,'v15');
""")


def test_management_shows_current_skill_body_and_revision_diff():
    boot = REGISTRY_BOOT.replace('JSON.stringify(principal)', "JSON.stringify({...superUser,permissions:[...superUser.permissions,'platform.environment.manage']})").replace(
        '"device_role":"worker"', '"device_role":"worker","deployment":"cloud"').replace(
        "return new Response('[]');", r"""
 if(path==='/api/v3/skill-categories')return new Response(JSON.stringify([{id:'channel-analysis',name:'频道分析',versions:[{id:'analysis',label:'xy-yt-report-v2',revision:1,status:'published'}],default_id:'analysis'}, {id:'package-production',name:'运营包生产',versions:[{id:'v15',label:'V15',revision:1,status:'published'},{id:'builtin-v14',label:'V14',revision:1,status:'published'}],default_id:'builtin-v14'}]));
 if(path.startsWith('/api/v3/skill-categories/package-production/versions/v15')) {
   const params = new URLSearchParams(path.split('?')[1]);
   const skill = params.get('skill') || 'xy-title-v15';
   const compare = params.has('compare_to');
   return new Response(JSON.stringify({skills:['xy-title-v15','xy-cover-v15'], skill,
     content:skill==='xy-cover-v15'?'new cover rule':'new title rule',
     compared_skill:compare?'xy-cover-v14':null, comparison_only:compare?['xy-cover-scene-v14']:[],
     diff:compare?'-old cover rule\n+new cover rule':null}));
 }
 return new Response('[]');
""")
    run_node(boot + r"""
await click('workflow-settings');
assert.match(page.nodes.get('viewRoot').innerHTML,/skill-catalog/);
assert.match(page.nodes.get('viewRoot').innerHTML,/添加版本/);
assert.match(page.nodes.get('viewRoot').innerHTML,/设为默认/);
await click('catalog-files','v15');
const drawer = () => page.nodes.get('drawerBody').innerHTML;
assert.match(drawer(),/本版 Skills（2）/);
assert.match(drawer(),/new title rule/);
assert.doesNotMatch(drawer(),/SKILL\.md|\.py|版本文件/);
await click('workflow-skill','v15',{skill:'xy-cover-v15',compare:''});
assert.match(drawer(),/xy-cover-v15 · 正文/);
assert.match(drawer(),/new cover rule/);
const target = {dataset:{id:'v15',skill:'xy-cover-v15'},value:'builtin-v14',matches:s=>s==='[data-workflow-compare]',classList:{contains:()=>false}};
await page.document.emit('change',{target});
assert.match(drawer(),/对照 Skill：xy-cover-v14/);
assert.match(drawer(),/仅对照版本包含：xy-cover-scene-v14/);
assert.match(drawer(),/-old cover rule/);
assert.match(drawer(),/\+new cover rule/);
const request=requests.find(([p])=>p.includes('compare_to=builtin-v14'));
assert.ok(request[0].includes('skill=xy-cover-v15'));
await click('catalog-default','v15');
await click('work-detail','work-a');
await click('v14-start','work-a');
const production=requests.find(([p,o])=>p.endsWith('/v14-runs')&&o.method==='POST');
assert.equal(JSON.parse(production[1].body).workflow_version_id,'v15');
""")
