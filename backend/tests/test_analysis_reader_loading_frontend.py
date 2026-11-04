from test_auth_frontend_contract import run_node,APP_FIXTURE


LOADING_FIXTURE=r"""
let release,count=0,fail=false;
const result={id:'run',status:'applied',created_at:'2026-11-04T00:00:00Z',input_snapshot:{model:'test'},result:{profile:'# 已加载的报告',diagnosis:'诊断',generation_spec:'规范'}};
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/analysis-runs/run'){count++;return new Promise(resolve=>release=()=>resolve(fail ? new Response(JSON.stringify({detail:'报告读取失败'}),{status:503}) : new Response(JSON.stringify(result))));}
 return defaultResponse(path);
});
await settle(page);
const button={dataset:{action:'view-analysis-result',id:'run'},textContent:'查看当前版本',disabled:false,closest:()=>null,querySelector:()=>null};
const click=()=>page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
"""


def test_view_immediately_shows_loading_and_avoids_duplicate_reads():
    run_node(APP_FIXTURE+LOADING_FIXTURE+r"""
const opening=click();await settle(page);
assert.equal(page.nodes.get('modalBackdrop').hidden,false);
assert.match(page.nodes.get('modalBody').innerHTML,/正在加载报告/);
assert.match(page.nodes.get('modalBody').innerHTML,/role="status"/);
assert.equal(button.disabled,true);
await click();assert.equal(count,1);
release();await opening;
assert.match(page.nodes.get('modalBody').innerHTML,/已加载的报告/);
assert.doesNotMatch(page.nodes.get('modalBody').innerHTML,/正在加载报告/);
assert.equal(button.disabled,false);assert.equal(button.textContent,'查看当前版本');
""")


def test_closed_loading_dialog_is_not_reopened_by_late_response():
    run_node(APP_FIXTURE+LOADING_FIXTURE+r"""
const opening=click();await settle(page);
await page.document.emit('click',{target:{closest:selector=>selector==='[data-close-modal]'?{}:null}});
release();await opening;
assert.equal(page.nodes.get('modalBackdrop').hidden,true);
assert.equal(page.nodes.get('modalBody').innerHTML,'');
""")


def test_failed_load_shows_error_and_retry_succeeds():
    run_node(APP_FIXTURE+LOADING_FIXTURE+r"""
fail=true;const opening=click();await settle(page);release();await opening;
assert.match(page.nodes.get('modalBody').innerHTML,/加载失败/);
assert.match(page.nodes.get('modalBody').innerHTML,/重试/);
assert.equal(button.disabled,false);
fail=false;const retry=click();await settle(page);release();await retry;
assert.match(page.nodes.get('modalBody').innerHTML,/已加载的报告/);assert.equal(count,2);
""")


def test_company_switch_cannot_reopen_pending_report():
    run_node(APP_FIXTURE+LOADING_FIXTURE+r"""
const opening=click();await settle(page);
await switchCompany(page);release();await opening;
assert.equal(page.nodes.get('modalBackdrop').hidden,true);
assert.doesNotMatch(page.nodes.get('modalBody').innerHTML,/已加载的报告/);
""")
