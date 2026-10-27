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


def test_management_shows_upload_and_reads_actual_file_diff():
    boot = REGISTRY_BOOT.replace('JSON.stringify(principal)', "JSON.stringify({...superUser,permissions:[...superUser.permissions,'platform.environment.manage']})").replace(
        '"device_role":"worker"', '"device_role":"worker","deployment":"cloud"').replace(
        "return new Response('[]');", r"""
 if(path.startsWith('/api/v3/workflow-versions/v15'))return new Response(JSON.stringify({
   files:['demo/SKILL.md'],content:'new skill',diff:'-old skill\n+new skill\n'}));
 return new Response('[]');
""")
    run_node(boot + r"""
await click('workflow-settings');
assert.match(page.nodes.get('viewRoot').innerHTML,/workflowUploadForm/);
assert.match(page.nodes.get('viewRoot').innerHTML,/完整 Skills ZIP/);
assert.match(page.nodes.get('viewRoot').innerHTML,/设为默认/);
await click('workflow-files','v15');
assert.match(page.nodes.get('drawerBody').innerHTML,/demo\/SKILL.md/);
await page.document.emit('change',{target:{dataset:{id:'v15'},value:'builtin-v14',matches:s=>s==='[data-workflow-compare]'}});
await page.document.emit('change',{target:{dataset:{id:'v15'},value:'demo/SKILL.md',matches:s=>s==='[data-workflow-file]'}});
assert.match(page.nodes.get('drawerBody').innerHTML,/-old skill/);
assert.match(page.nodes.get('drawerBody').innerHTML,/\+new skill/);
const request=requests.find(([p])=>p.includes('path=demo%2FSKILL.md'));
assert.ok(request[0].includes('compare_to=builtin-v14'));
""")
