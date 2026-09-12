import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = """
const tenant = {id: 't1', company_name: '甲公司', short_name: '甲'};
const principal = {user_id:'u1', display_name:'小雨', login_name:'xiaoyu', platform_role:null,
  tenant_id:'t1', membership_role:'owner', current_tenant:tenant,
  memberships:[{tenant_id:'t1',company_name:'甲公司',short_name:'甲',role_code:'owner'}],
  switchable_tenants:[tenant], device:null, permissions:['user.read','user.manage','channel.read']};
const superUser = {...principal, platform_role:'super_admin', membership_role:null, memberships:[],
  device:{id:'d1',name:'mac',display_name:'代码机',trust_level:'super_code_machine'},
  permissions:['user.read','user.manage','platform.tenant.manage','platform.device.manage'],
  switchable_tenants:[tenant,{id:'t2',company_name:'乙公司',short_name:'乙'}]};
const assert = require('node:assert/strict');
const auth = require(process.argv[1] + '/assets/auth-state.js');
"""


def run_node(program):
    result = subprocess.run(
        ["node", "-e", FIXTURE + "\n(async()=>{\n" + program + "\n})().catch(e=>{console.error(e);process.exitCode=1});", str(ROOT)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_bootstrap_only_resolves_identity_and_leaves_401_at_login():
    run_node("""
const paths=[];
const result=await auth.resolveBootstrap(async path=>{paths.push(path);throw Object.assign(new Error('登录'),{status:401});});
assert.equal(result,null); assert.equal(auth.current(),null);
assert.equal(auth.can('channel.read'),false); assert.deepEqual(paths,['/auth/me']);
await assert.rejects(auth.resolveBootstrap(async()=>{throw Object.assign(new Error('offline'),{status:503});}),/offline/);
assert.equal(auth.current(),null);
""")


def test_password_login_keeps_identity_only_in_memory_and_logout_does_not_bootstrap():
    run_node("""
const paths=[];
await auth.login(async(path,options)=>{paths.push(path);assert.deepEqual(JSON.parse(options.body),{login_name:'xiaoyu',password:'local-test'});return principal;},'xiaoyu','local-test');
assert.equal(auth.current().display_name,'小雨'); assert.equal(auth.can('user.manage'),true);
await auth.logout(async path=>{assert.equal(auth.current(),null);paths.push(path);return {status:'ok'};});
assert.equal(auth.can('user.manage'),false);assert.deepEqual(paths,['/auth/login','/auth/logout']);
""")


def test_permissions_require_real_actor_and_device_and_owner_scope():
    run_node("""
await auth.resolveBootstrap(async()=>({...principal,device:superUser.device}));
assert.equal(auth.access().platform,false); assert.equal(auth.access().users,true);
assert.equal(auth.usersPath('t1'),'/tenant/users');
assert.throws(()=>auth.usersPath('t2'),/权限/);
assert.equal(auth.canManageUser({id:'owner',role_code:'owner',platform_role:null}),false);
await auth.resolveBootstrap(async()=>({...principal,membership_role:'admin'}));
assert.equal(auth.access().users,false);
await auth.resolveBootstrap(async()=>({...superUser,device:null}));
assert.equal(auth.access().switchTenant,true);assert.equal(auth.access().platform,false);
assert.equal(auth.access().users,false);
await auth.resolveBootstrap(async()=>superUser);
assert.equal(auth.access().platform,true);assert.equal(auth.access().devices,true);
assert.equal(auth.usersPath('t2'),'/platform/tenants/t2/users');
await auth.resolveBootstrap(async()=>({...superUser,permissions:[]}));
assert.equal(auth.access().users,false); assert.equal(auth.access().devices,false);
""")


def test_builder_runtime_role_does_not_grant_platform_navigation_to_normal_user():
    run_node("""
await auth.resolveBootstrap(async()=>({...principal,device:superUser.device}));
assert.equal(auth.canView('settings','builder'),false);assert.equal(auth.canView('logs','builder'),false);
await auth.resolveBootstrap(async()=>({...superUser,permissions:[...superUser.permissions,'platform.environment.manage','audit.read']}));
assert.equal(auth.canView('settings','builder'),true);assert.equal(auth.canView('logs','builder'),true);
assert.equal(auth.canView('skills','worker'),false);
""")


def test_switch_tenant_clears_old_context_preserves_actor_and_uses_server_options():
    run_node("""
await auth.resolveBootstrap(async()=>({...superUser,device:null}));
const changes=[];auth.subscribe(user=>changes.push(user?.tenant_id||null));
await auth.switchTenant(async(path,options)=>{
  assert.equal(auth.current(),null);assert.equal(path,'/auth/switch-tenant');
  assert.deepEqual(JSON.parse(options.body),{tenant_id:'t2'});
  return {...superUser,device:null,tenant_id:'t2',current_tenant:superUser.switchable_tenants[1]};
},'t2');
assert.equal(auth.current().user_id,'u1');assert.equal(auth.current().tenant_id,'t2');
assert.deepEqual(changes,[null,'t2']);
await assert.rejects(auth.switchTenant(async()=>{},'unknown'),/主账号/);
""")


def test_shared_request_sends_cookie_clears_401_and_discards_old_tenant_response():
    run_node("""
await auth.resolveBootstrap(async()=>principal);
const data=await auth.request(async(url,options)=>{
 assert.equal(url,'/api/v3/channels');assert.equal(options.credentials,'same-origin');assert.equal(options.cache,'no-store');
 return new Response(JSON.stringify(['ok']),{status:200});
},'/channels');assert.deepEqual(data,['ok']);
let finish; const stale=auth.request(()=>new Promise(resolve=>{finish=resolve;}),'/channels');
const rejected=assert.rejects(stale,error=>error.name==='AbortError');
auth.clear();finish(new Response(JSON.stringify(['old-company']),{status:200}));await rejected;
await auth.resolveBootstrap(async()=>principal);
await assert.rejects(auth.request(async()=>new Response(JSON.stringify({detail:'请先登录'}),{status:401}),'/channels'),error=>error.status===401);
assert.equal(auth.current(),null);
""")


def test_signed_out_shared_request_cannot_start_a_business_call():
    run_node("""
let called=false;
await assert.rejects(auth.request(async()=>{called=true;return new Response('[]');},'/channels'),error=>error.status===401);
assert.equal(called,false);
""")


def test_shared_request_keeps_a_batch_bound_to_its_starting_identity():
    run_node("""
await auth.resolveBootstrap(async()=>principal);
const revision=auth.capture();assert.equal(auth.isCurrent(revision),true);
await auth.request(async(url,options)=>{
 assert.equal(Object.hasOwn(options,'expectedRevision'),false);
 return new Response('{}');
},'/tasks/a1/dispatch',{method:'POST',expectedRevision:revision});
await auth.resolveBootstrap(async()=>({...superUser,tenant_id:'t2'}));
assert.equal(auth.isCurrent(revision),false);let called=false;
await assert.rejects(auth.request(async()=>{called=true;return new Response('{}');},'/tasks/a2/dispatch',
 {method:'POST',expectedRevision:revision}),error=>error.name==='AbortError');
assert.equal(called,false);
""")


def test_account_center_owner_uses_only_tenant_endpoint_and_hides_platform_controls():
    run_node("""
await auth.resolveBootstrap(async()=>principal);
const center=require(process.argv[1]+'/assets/account-center.js');const paths=[];
const model=await center.load(async path=>{paths.push(path);return [
 {id:'u1',display_name:'负责人',login_name:'owner',status:'active',role_code:'owner',membership_status:'active',platform_role:null,tenant_id:'t1',lease_expires_at:null},
 {id:'u2',display_name:'运营',login_name:'op',status:'active',role_code:'operator',membership_status:'active',platform_role:null,tenant_id:'t1',lease_expires_at:null}];});
assert.deepEqual(paths,['/tenant/users']);const html=center.render(model);
assert.match(html,/负责人/);assert.match(html,/data-account-action="edit-user" data-id="u2"/);
assert.doesNotMatch(html,/data-account-action="edit-user" data-id="u1"/);
assert.doesNotMatch(html,/new-tenant|transfer-owner|revoke-binding|乙公司/);
""")


def test_account_center_platform_lists_companies_users_bindings_without_http_enrollment():
    run_node("""
await auth.resolveBootstrap(async()=>superUser);const center=require(process.argv[1]+'/assets/account-center.js');const paths=[];
const model=await center.load(async path=>{paths.push(path);
 if(path==='/platform/tenants')return [{...tenant,status:'active',lease_expires_at:'2030-01-01T00:00:00Z'}];
 if(path==='/platform/device-bindings')return [{id:'b1',device_id:'device-001',device_name:'客户前台 Mac',device_status:'inactive',tenant_id:'t1',tenant_name:'甲公司',user_id:'u1',user_display_name:'李运营',login_name:'li.operator',binding_status:'revoked',login_mode:'password',expires_at:null}];
 if(path==='/platform/tenants/t1/users')return [];throw new Error(path);
});
assert.deepEqual(paths.sort(),['/platform/device-bindings','/platform/tenants','/platform/tenants/t1/users']);
const html=center.render(model);assert.match(html,/new-tenant/);
assert.match(html,/客户前台 Mac/);assert.match(html,/device-001/);assert.match(html,/停用/);
assert.match(html,/李运营/);assert.match(html,/li[.]operator/);assert.match(html,/账号密码/);
assert.doesNotMatch(html,/data-account-action="revoke-binding"/);
assert.match(html,/超级代码机.*本地登记/);assert.doesNotMatch(html,/data-account-action="(?:create|new)-binding"/);
""")


def test_device_manager_without_selected_tenant_can_open_binding_list():
    run_node("""
await auth.resolveBootstrap(async()=>({...superUser,tenant_id:null,current_tenant:null,permissions:['platform.device.manage']}));
const center=require(process.argv[1]+'/assets/account-center.js');const paths=[];
const model=await center.load(async path=>{paths.push(path);return [];});
assert.deepEqual(paths,['/platform/device-bindings']);assert.match(center.render(model),/设备绑定/);
""")


def test_account_center_marks_active_accounts_with_past_leases_as_expired():
    run_node("""
await auth.resolveBootstrap(async()=>superUser);const center=require(process.argv[1]+'/assets/account-center.js');
const html=center.render({tenants:[{...tenant,status:'active',lease_expires_at:'2020-01-01T00:00:00Z'}],tenantId:'t1',users:[{id:'u2',display_name:'过期用户',status:'active',role_code:'operator',membership_status:'active',lease_expires_at:'2020-01-01T00:00:00Z'}],bindings:[]});
assert.equal((html.match(/已到期/g)||[]).length,2);
""")


def test_account_forms_emit_api_payloads_with_aware_dates_and_no_accidental_owner_demotion():
    run_node("""
await auth.resolveBootstrap(async()=>superUser);const center=require(process.argv[1]+'/assets/account-center.js');
const context={tenantId:'t1',users:[{id:'u1',role_code:'owner',platform_role:null}]};
const command=center.command('edit-user',{user_id:'u1',display_name:'负责人',login_name:'owner',status:'active',lease_expires_at:'',suspended_reason:''},context);
assert.equal(command.path,'/platform/tenants/t1/users/u1');assert.equal(command.options.method,'PATCH');
assert.deepEqual(JSON.parse(command.options.body),{display_name:'负责人',login_name:'owner',status:'active',lease_expires_at:null,suspended_reason:null});
const create=center.command('new-tenant',{company_name:'甲公司',short_name:'甲',status:'active',lease_expires_at:'2030-01-02T12:00',owner_display_name:'李',owner_login_name:'li',owner_password:'fixture-only',owner_lease_expires_at:'',contact_name:'李',contact_phone:'',plan_code:'',remark:''},{});
const body=JSON.parse(create.options.body);assert.equal(create.path,'/platform/tenants');
assert.match(body.lease_expires_at,/Z$/);assert.equal(body.owner.password,'fixture-only');assert.equal(body.owner.lease_expires_at,null);
assert.equal(Object.hasOwn(body,'owner_password'),false);
assert.throws(()=>center.command('new-binding',{},context),/操作/);
""")


def test_account_actions_cover_user_roles_password_owner_transfer_and_binding_revoke():
    run_node("""
await auth.resolveBootstrap(async()=>superUser);const center=require(process.argv[1]+'/assets/account-center.js');
const context={tenantId:'t1',users:[{id:'u2',role_code:'operator',platform_role:null}]};
const transfer=center.command('transfer-owner',{user_id:'u2',previous_owner_role:'admin'},context);
assert.equal(transfer.path,'/platform/tenants/t1/owner');assert.deepEqual(JSON.parse(transfer.options.body),{user_id:'u2',previous_owner_role:'admin'});
const password=center.command('reset-password',{user_id:'u2',password:'fixture-only'},context);
assert.equal(password.path,'/platform/tenants/t1/users/u2/password');assert.deepEqual(JSON.parse(password.options.body),{password:'fixture-only'});
const revoke=center.command('revoke-binding',{binding_id:'b1',reason:'设备停用'},context);
assert.equal(revoke.path,'/platform/device-bindings/b1/revoke');assert.deepEqual(JSON.parse(revoke.options.body),{reason:'设备停用'});
await auth.resolveBootstrap(async()=>principal);
const user=center.command('new-user',{display_name:'运营',login_name:'op',password:'fixture-only',role_code:'operator',status:'active',lease_expires_at:''},{tenantId:'t1'});
assert.equal(user.path,'/tenant/users');assert.equal(JSON.parse(user.options.body).role_code,'operator');
assert.throws(()=>center.command('new-user',{role_code:'owner'},{tenantId:'t1'}),/角色/);
assert.throws(()=>center.command('edit-tenant',{},{tenantId:'t1'}),/权限/);
""")


def test_owner_role_edit_omits_unchanged_shared_account_profile_and_exact_lease():
    run_node("""
process.env.TZ='UTC';await auth.resolveBootstrap(async()=>principal);
const center=require(process.argv[1]+'/assets/account-center.js');
const user={id:'u2',display_name:'共用用户',login_name:'shared',status:'active',role_code:'operator',membership_status:'active',platform_role:null,lease_expires_at:'2030-01-02T12:00:45Z'};
const command=center.command('edit-user',{user_id:'u2',display_name:'共用用户',login_name:'shared',status:'active',role_code:'viewer',membership_status:'active',lease_expires_at:'2030-01-02T12:00',suspended_reason:''},{tenantId:'t1',users:[user]});
assert.equal(command.path,'/tenant/users/u2');assert.deepEqual(JSON.parse(command.options.body),{role_code:'viewer'});
""")


def test_tenant_edit_omits_unchanged_exact_lease_for_the_edited_company():
    run_node("""
process.env.TZ='UTC';await auth.resolveBootstrap(async()=>superUser);
const center=require(process.argv[1]+'/assets/account-center.js');
const company={...tenant,status:'active',lease_expires_at:'2030-01-02T12:00:45.789Z'};
const context={tenantId:'t2',tenants:[company,{id:'t2',lease_expires_at:'2031-01-01T12:00:00Z'}]};
const values={tenant_id:'t1',company_name:'甲公司新名称',short_name:'甲',status:'active',lease_expires_at:'2030-01-02T12:00'};
const unchanged=center.command('edit-tenant',values,context);
assert.equal(unchanged.path,'/platform/tenants/t1');
assert.equal(JSON.parse(unchanged.options.body).company_name,'甲公司新名称');
assert.equal(Object.hasOwn(JSON.parse(unchanged.options.body),'lease_expires_at'),false);
const changed=center.command('edit-tenant',{...values,lease_expires_at:'2030-01-02T12:01'},context);
assert.equal(JSON.parse(changed.options.body).lease_expires_at,'2030-01-02T12:01:00.000Z');
""")


def test_account_forms_show_required_owner_and_password_fields_without_saved_passwords():
    run_node("""
await auth.resolveBootstrap(async()=>superUser);const center=require(process.argv[1]+'/assets/account-center.js');
const create=center.form('new-tenant',{});assert.match(create,/name="owner_login_name"/);
assert.match(create,/name="owner_password"[^>]*type="password"/);
assert.match(create,/name="lease_expires_at"[^>]*required/);
const edit=center.form('edit-user',{tenantId:'t1',users:[]},{id:'u1',display_name:'负责人',role_code:'owner',status:'active',platform_role:null});
assert.doesNotMatch(edit,/name="role_code"/);assert.doesNotMatch(edit,/name="password"/);
const reset=center.form('reset-password',{},{id:'u2',display_name:'运营',role_code:'operator',platform_role:null});
assert.match(reset,/autocomplete="new-password"/);assert.match(reset,/会话/);
""")


class ShellParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = {}
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.elements[attrs["id"]] = (tag, attrs)
        if tag == "script":
            self.scripts.append(attrs.get("src", "").split("?")[0])


def test_html_starts_with_login_only_and_accessible_account_controls():
    shell = ShellParser((ROOT / "index.html").read_text())
    assert "hidden" in shell.elements["appShell"][1]
    assert shell.elements["loginForm"][0] == "form"
    assert shell.elements["loginName"][1]["autocomplete"] == "username"
    assert shell.elements["loginPassword"][1]["type"] == "password"
    assert shell.elements["loginPassword"][1]["autocomplete"] == "current-password"
    assert shell.elements["loginError"][1]["role"] == "alert"
    assert shell.elements["accountButton"][1]["aria-controls"] == "accountMenu"
    assert shell.elements["refreshView"][1].get("aria-label")
    assert "hidden" in shell.elements["tenantBanner"][1]
    assert shell.scripts.index("/assets/auth-state.js") < shell.scripts.index("/assets/account-center.js") < shell.scripts.index("/assets/app.js")


def test_real_app_bootstrap_does_not_load_business_before_login_and_401_clears_every_surface():
    run_node("""
let signedIn=false, failBusiness=false;const paths=[];
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const page=start(process.argv[1],auth,async(path,options)=>{
  paths.push(path);
  if(path==='/api/v3/auth/login'){signedIn=true;return new Response(JSON.stringify(principal));}
  if(path==='/api/v3/auth/logout'){signedIn=false;return new Response('{"status":"ok"}');}
  if(path==='/api/v3/auth/me')return new Response(JSON.stringify(signedIn?principal:{detail:'请先登录'}),{status:signedIn?200:401});
  if(failBusiness)return new Response('{"detail":"请先登录"}',{status:401});
  if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true},"web_port":8200}');
  if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
  if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
  return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
assert.deepEqual(paths,['/api/v3/auth/me']);assert.equal(page.nodes.get('appShell').hidden,true);
assert.equal(page.nodes.get('loginShell').hidden,false);
page.nodes.get('loginName').value='xiaoyu';page.nodes.get('loginPassword').value='fixture-only';
await page.nodes.get('loginForm').emit('submit');for(let i=0;i<4;i++)await page.tick();
assert.equal(page.nodes.get('appShell').hidden,false);assert.equal(page.nodes.get('loginShell').hidden,true);
assert.match(page.nodes.get('viewRoot').innerHTML,/运营频道/);
assert.match(page.nodes.get('accountIdentity').textContent,/小雨/);
assert.match(page.nodes.get('accountContext').textContent,/甲公司/);
assert.equal(page.nodes.get('loginPassword').value,'');
for(const id of ['modalBody','drawerBody','toastStack'])page.nodes.get(id).innerHTML='甲公司秘密';
failBusiness=true;await page.nodes.get('refreshView').emit('click');await page.tick();
assert.equal(page.nodes.get('appShell').hidden,true);assert.equal(auth.current(),null);
for(const id of ['viewRoot','modalBody','drawerBody','toastStack'])assert.equal(page.nodes.get(id).innerHTML,'');
const count=paths.length;await page.document.emit('visibilitychange');await page.tick();assert.equal(paths.length,count);
""")


def test_real_app_super_without_tenant_keeps_banner_and_logout_returns_to_login():
    run_node("""
const paths=[];const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const page=start(process.argv[1],auth,async path=>{paths.push(path);return new Response(JSON.stringify(path.endsWith('/logout')?{status:'ok'}:{...superUser,tenant_id:null,current_tenant:null}));});
for(let i=0;i<4;i++)await page.tick();
assert.deepEqual(paths,['/api/v3/auth/me']);assert.equal(page.nodes.get('appShell').hidden,false);
assert.equal(page.nodes.get('tenantBanner').hidden,false);assert.match(page.nodes.get('tenantBanner').textContent,/超级管理员模式/);
assert.match(page.nodes.get('tenantSelect').innerHTML,/甲公司/);assert.match(page.nodes.get('tenantSelect').innerHTML,/乙公司/);
await page.nodes.get('logoutButton').emit('click');await page.tick();
assert.equal(page.nodes.get('loginShell').hidden,false);assert.equal(page.nodes.get('appShell').hidden,true);
assert.equal(page.nodes.get('accountIdentity').textContent,'');assert.equal(page.nodes.get('tenantSelect').innerHTML,'');
assert.deepEqual(paths,['/api/v3/auth/me','/api/v3/auth/logout']);
""")


APP_FIXTURE = """
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const companyB={...superUser,tenant_id:'t2',current_tenant:superUser.switchable_tenants[1]};
const paths=[];let serverUser=superUser;
function defaultResponse(path) {
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(serverUser));
 if(path==='/api/v3/auth/switch-tenant'){serverUser=companyB;return new Response(JSON.stringify(serverUser));}
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true},"web_port":8200}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path.startsWith('/api/v3/tasks/overview'))return new Response(JSON.stringify(serverUser.tenant_id==='t1'
  ? [{task_id:'a1',task_status:'pending_dispatch'},{task_id:'a2',task_status:'pending_dispatch'}] : []));
 return new Response('[]');
}
async function settle(page) {for(let i=0;i<4;i++)await page.tick();}
function clickAction(page,action,data={}) {
 const button={dataset:{action,...data},closest:()=>null};
 return page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
}
async function switchCompany(page) {
 page.nodes.get('tenantSelect').value='t2';await page.nodes.get('tenantSwitchForm').emit('submit');
}
"""


def test_real_app_account_center_selects_company_before_showing_members_and_access_devices():
    run_node(APP_FIXTURE + """
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/platform/tenants')return new Response(JSON.stringify(superUser.switchable_tenants));
 if(path==='/api/v3/platform/tenants/t1/users')return new Response(JSON.stringify([
  {id:'u1',display_name:'李运营',login_name:'li.operator',status:'active',role_code:'owner',membership_status:'active',platform_role:null,tenant_id:'t1',lease_expires_at:null}
 ]));
 if(path==='/api/v3/platform/device-bindings?tenant_id=t1')return new Response(JSON.stringify([
  {id:'b1',device_id:'device-001',device_name:'客户前台 Mac',device_status:'inactive',tenant_id:'t1',tenant_name:'甲公司',user_id:'u1',user_display_name:'李运营',login_name:'li.operator',binding_status:'active',login_mode:'auto_login',expires_at:null},
  {id:'b2',device_id:'device-002',device_name:'已撤销设备',device_status:'active',tenant_id:'t1',tenant_name:'甲公司',user_id:'u1',user_display_name:'李运营',login_name:'li.operator',binding_status:'revoked',login_mode:'password',expires_at:null}
 ]));
 return defaultResponse(path);
});
await settle(page);
await page.document.emit('click',{target:{closest:selector=>selector==='[data-view]'?{dataset:{view:'accounts'}}:null}});
await settle(page);
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/公司\\s*→\\s*成员/);assert.match(html,/客户访问设备/);
assert.match(html,/客户前台 Mac/);assert.match(html,/device-001/);
assert.match(html,/李运营/);assert.match(html,/li\\.operator/);assert.match(html,/甲公司/);
assert.match(html,/停用/);assert.match(html,/免登录/);
assert.equal((html.match(/data-account-action="revoke-binding"/g)||[]).length,1);
assert(paths.includes('/api/v3/platform/device-bindings?tenant_id=t1'));
""")


def test_settings_keeps_platform_device_inventory_distinct_from_ai_workers():
    run_node(APP_FIXTURE + """
serverUser={...superUser,permissions:[...superUser.permissions,'platform.environment.manage']};
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"builder"}');
 if(path==='/api/v3/devices')return new Response(JSON.stringify([
  {id:'device-001',device_key:'client:001',name:'客户前台 Mac',alias:null,hostname:'frontdesk.local',device_role:'worker',login_user:'frontdesk',thunderbolt_address:null,lan_address:'192.0.2.10',purpose:'客户访问',status:'active',last_seen_at:null}
 ]));
 return defaultResponse(path);
});
await settle(page);
await page.document.emit('click',{target:{closest:selector=>selector==='[data-view]'?{dataset:{view:'settings'}}:null}});
await settle(page);
await page.document.emit('click',{target:{closest:selector=>selector==='[data-settings-tab]'?{dataset:{settingsTab:'devices'}}:null}});
await settle(page);
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/平台设备总表/);assert.match(html,/非 AI Worker/);
assert.match(html,/device-001/);assert.match(html,/客户前台 Mac/);
""")


def test_real_app_bulk_dispatch_does_not_send_next_old_id_after_tenant_switch():
    run_node(APP_FIXTURE + """
let release;
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/tasks/a1/dispatch')return new Promise(resolve=>{release=()=>resolve(new Response('{}'));});
 return defaultResponse(path);
});
await settle(page);const pending=clickAction(page,'dispatch-all');await page.tick();
assert.equal(typeof release,'function');await switchCompany(page);
assert.equal(auth.current().tenant_id,'t2');const count=paths.length;
release();await pending;
assert.deepEqual(paths.filter(path=>path.endsWith('/dispatch')),['/api/v3/tasks/a1/dispatch']);
assert.equal(paths.length,count);assert.match(page.nodes.get('tenantBanner').textContent,/乙公司/);
""")


@pytest.mark.parametrize("first_status", [200, 409])
def test_real_app_bulk_dispatch_completes_under_one_identity(first_status):
    run_node(APP_FIXTURE + f"const firstStatus={first_status};" + """
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/tasks/a1/dispatch')return new Response('{"detail":"已下发"}',{status:firstStatus});
 return defaultResponse(path);
});
await settle(page);await clickAction(page,'dispatch-all');
assert.deepEqual(paths.filter(path=>path.endsWith('/dispatch')),['/api/v3/tasks/a1/dispatch','/api/v3/tasks/a2/dispatch']);
assert.match(page.nodes.get('viewRoot').innerHTML,/工单列表/);assert.equal(auth.current().tenant_id,'t1');
""")


@pytest.mark.parametrize("failure", ["401", "abort"])
def test_real_app_bulk_dispatch_stops_on_auth_failure_or_abort(failure):
    run_node(APP_FIXTURE + f"const failure={json.dumps(failure)};" + """
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/tasks/a1/dispatch'){
  if(failure==='abort')throw new DOMException('cancelled','AbortError');
  return new Response('{"detail":"请先登录"}',{status:401});
 }
 return defaultResponse(path);
});
await settle(page);const count=paths.length;await clickAction(page,'dispatch-all');
assert.deepEqual(paths.slice(count),['/api/v3/tasks/a1/dispatch']);
""")


@pytest.mark.parametrize("failure", ["network", "503"])
def test_real_app_uncertain_switch_reconfirms_server_identity_before_business(failure):
    run_node(APP_FIXTURE + f"const failure={json.dumps(failure)};" + """
let releaseMe, confirm=false;const business=[];
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/auth/switch-tenant'){
  serverUser=companyB;confirm=true;
  if(failure==='network')throw new TypeError('response lost');
  return new Response('{"detail":"upstream failed"}',{status:503});
 }
 if(path==='/api/v3/auth/me'&&confirm)return new Promise(resolve=>{releaseMe=()=>resolve(new Response(JSON.stringify(serverUser)));});
 if(!path.includes('/auth/'))business.push({server:serverUser.tenant_id,shown:auth.current()?.tenant_id});
 return defaultResponse(path);
});
await settle(page);const count=paths.length;const pending=switchCompany(page);await settle(page);
assert.deepEqual(paths.slice(count),['/api/v3/auth/switch-tenant','/api/v3/auth/me']);
assert.equal(auth.current(),null);assert.equal(page.nodes.get('viewRoot').innerHTML,'');
assert.equal(page.nodes.get('appShell').hidden,true);assert.equal(typeof releaseMe,'function');
releaseMe();await pending;
assert.equal(auth.current().tenant_id,'t2');assert.equal(page.nodes.get('appShell').hidden,false);
assert.match(page.nodes.get('tenantBanner').textContent,/乙公司/);
assert.ok(business.some(item=>item.server==='t2'));
assert.ok(business.every(item=>item.server===item.shown));
""")


@pytest.mark.parametrize("confirmation_status", [401, 503, "network"])
def test_real_app_failed_switch_confirmation_stays_empty_and_sends_no_business(confirmation_status):
    run_node(APP_FIXTURE + f"const confirmationStatus={json.dumps(confirmation_status)};" + """
let confirm=false;
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/auth/switch-tenant'){serverUser=companyB;confirm=true;throw new TypeError('response lost');}
 if(path==='/api/v3/auth/me'&&confirm){
  if(confirmationStatus==='network')throw new TypeError('cannot confirm');
  return new Response('{"detail":"cannot confirm"}',{status:confirmationStatus});
 }
 return defaultResponse(path);
});
await settle(page);const count=paths.length;await switchCompany(page);
assert.deepEqual(paths.slice(count),['/api/v3/auth/switch-tenant','/api/v3/auth/me']);
assert.equal(auth.current(),null);assert.equal(page.nodes.get('appShell').hidden,true);
assert.equal(page.nodes.get('loginShell').hidden,false);
for(const id of ['viewRoot','modalBody','drawerBody','toastStack'])assert.equal(page.nodes.get(id).innerHTML,'');
""")


def test_real_app_uncommitted_switch_uses_confirmed_identity_and_shows_failure():
    run_node(APP_FIXTURE + """
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/auth/switch-tenant')throw new TypeError('未送达');
 return defaultResponse(path);
});
await settle(page);const count=paths.length;await switchCompany(page);
assert.deepEqual(paths.slice(count,count+2),['/api/v3/auth/switch-tenant','/api/v3/auth/me']);
assert.equal(auth.current().tenant_id,'t1');assert.match(page.nodes.get('tenantBanner').textContent,/甲公司/);
assert.equal(page.nodes.get('tenantSwitchError').hidden,false);assert.match(page.nodes.get('tenantSwitchError').textContent,/未送达/);
""")


@pytest.mark.parametrize("form_id", ["dramaBulkForm", "appIconForm"])
@pytest.mark.parametrize("switch_tenant", [True, False])
def test_real_app_file_submission_stays_bound_to_identity_during_file_read(form_id, switch_tenant):
    run_node(APP_FIXTURE + f"const formId={json.dumps(form_id)}, switchTenant={json.dumps(switch_tenant)};" + """
let release;
const file={name:'fixture',text:()=>new Promise(resolve=>{release=()=>resolve('甲公司的 CSV');})};
class FixtureFormData {entries(){return [][Symbol.iterator]();}}
class FixtureFileReader {readAsDataURL(){release=()=>{this.result='data:image/png;base64,fixture';this.onload();};}}
const page=start(process.argv[1],auth,async(path,options)=>{paths.push(path);return defaultResponse(path);},
 {FormData:FixtureFormData,FileReader:FixtureFileReader});
await settle(page);
const form={id:formId,matches:()=>false,elements:{csv_file:{files:[file]},icon_file:{files:[file]}}};
const pending=page.document.emit('submit',{target:form});await page.tick();
assert.equal(typeof release,'function');if(switchTenant)await switchCompany(page);const count=paths.length;
release();await pending;
if(switchTenant){assert.equal(paths.length,count);assert.equal(auth.current().tenant_id,'t2');}
else {
 const endpoint=formId==='dramaBulkForm'?'/api/v3/dramas/bulk-csv':'/api/v3/settings/app-icon';
 assert.equal(paths.filter(path=>path===endpoint).length,1);assert.equal(auth.current().tenant_id,'t1');
}
""")


@pytest.mark.parametrize("switch_tenant", [True, False])
def test_real_app_copy_progress_stays_bound_to_identity_during_clipboard_wait(switch_tenant):
    run_node(APP_FIXTURE + f"const switchTenant={json.dumps(switch_tenant)};" + """
let release;const item={package_id:'pa',chinese_title:'甲公司剧目',titles:[{id:'title-a',variant_number:1,localized_title:'甲公司标题'}]};
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/packages/operations-overview')return new Response(JSON.stringify([item]));
 return defaultResponse(path);
},{navigator:{clipboard:{writeText:value=>{assert.equal(value,'甲公司标题');return new Promise(resolve=>{release=resolve;});}}}});
await settle(page);await clickAction(page,'package-page-detail',{id:'pa'});
assert.match(page.nodes.get('viewRoot').innerHTML,/data-copy-key="pa:detail-title-1"/);
const pending=clickAction(page,'copy-package-field',{copyKey:'pa:detail-title-1',packageId:'pa',outputType:'title',outputId:'title-a'});
await page.tick();assert.equal(typeof release,'function');if(switchTenant)await switchCompany(page);const count=paths.length;
release();await pending;
if(switchTenant){assert.equal(paths.length,count);assert.equal(auth.current().tenant_id,'t2');}
else {assert.deepEqual(paths.slice(count),['/api/v3/packages/pa/copy-progress']);assert.equal(auth.current().tenant_id,'t1');}
""")


@pytest.mark.parametrize("me_result", [200, 401, 503, "network", "abort"])
@pytest.mark.parametrize("switch_tenant", [True, False])
def test_real_app_account_save_identity_refresh_is_bound_to_its_revision(me_result, switch_tenant):
    run_node(APP_FIXTURE + f"const meResult={json.dumps(me_result)}, switchTenant={json.dumps(switch_tenant)};" + """
let saved=false, releaseMe;
const companies=superUser.switchable_tenants.map(item=>({...item,status:'active',lease_expires_at:'2030-01-02T12:00:45.789Z'}));
const savedCompany={...companies[0],company_name:'甲公司更新'};
class FixtureFormData {constructor(form){this.values=form.values;}entries(){return Object.entries(this.values);}}
const page=start(process.argv[1],auth,async(path,options)=>{
 paths.push(path);
 if(path==='/api/v3/platform/tenants')return new Response(JSON.stringify(companies));
 if(path==='/api/v3/platform/tenants/t1'&&options.method==='PATCH'){
  saved=true;return new Response(JSON.stringify(savedCompany));
 }
 if(path==='/api/v3/auth/me'&&saved)return new Promise((resolve,reject)=>{
  releaseMe=()=>{
   if(meResult==='network')return reject(new TypeError('identity lookup offline'));
   if(meResult==='abort')return reject(new DOMException('identity lookup cancelled','AbortError'));
   resolve(new Response(JSON.stringify(meResult===200?{...superUser,current_tenant:savedCompany}:{detail:'identity lookup failed'}),{status:meResult}));
  };
 });
 return defaultResponse(path);
},{FormData:FixtureFormData});
await settle(page);await page.nodes.get('accountManage').emit('click');
assert.match(page.nodes.get('viewRoot').innerHTML,/账号租约/);
const editButton={dataset:{accountAction:'edit-tenant',id:'t1'}};
await page.document.emit('click',{target:{closest:selector=>selector==='[data-account-action]'?editButton:null}});
assert.match(page.nodes.get('modalBody').innerHTML,/id="accountAdminForm"/);
const submit=page.document.createElement();page.nodes.set('accountFormError',page.document.createElement());
const form={id:'accountAdminForm',dataset:{accountForm:'edit-tenant'},querySelector:()=>submit,querySelectorAll:()=>[],
 values:{tenant_id:'t1',company_name:'甲公司更新',short_name:'甲',status:'active',lease_expires_at:'2030-01-02T12:00'}};
const pending=page.document.emit('submit',{target:form});await page.tick();
assert.equal(saved,true);assert.equal(typeof releaseMe,'function');
assert.deepEqual(paths.slice(-2),['/api/v3/platform/tenants/t1','/api/v3/auth/me']);
if(switchTenant)await switchCompany(page);
const confirmed=auth.current(), count=paths.length, content=page.nodes.get('viewRoot').innerHTML;
releaseMe();await pending;
if(switchTenant){
 assert.equal(auth.current(),confirmed);assert.equal(auth.current().tenant_id,'t2');
 assert.match(page.nodes.get('tenantBanner').textContent,/乙公司/);
 assert.equal(page.nodes.get('viewRoot').innerHTML,content);assert.equal(paths.length,count);
 assert.equal(page.nodes.get('appShell').hidden,false);assert.equal(page.nodes.get('loginShell').hidden,true);
}else if(meResult===401){
 assert.equal(auth.current(),null);assert.equal(page.nodes.get('appShell').hidden,true);
 assert.equal(page.nodes.get('loginShell').hidden,false);assert.equal(paths.length,count);
 for(const id of ['viewRoot','modalBody','drawerBody','toastStack'])assert.equal(page.nodes.get(id).innerHTML,'');
}else if(meResult===200){
 assert.equal(auth.current().current_tenant.company_name,'甲公司更新');
 assert.match(page.nodes.get('tenantBanner').textContent,/甲公司更新/);assert.match(page.nodes.get('viewRoot').innerHTML,/账号租约/);
}else{
 assert.equal(auth.current(),confirmed);assert.equal(page.nodes.get('viewRoot').innerHTML,content);
 assert.equal(page.nodes.get('appShell').hidden,false);assert.equal(page.nodes.get('loginShell').hidden,true);
 assert.equal(paths.length,count);
}
""")


def test_overlapping_identity_refresh_does_not_clear_newer_confirmed_profile():
    run_node("""
await auth.resolveBootstrap(async()=>principal);let release;
const older=auth.resolveBootstrap((path,options)=>auth.request(()=>new Promise(resolve=>{release=resolve;}),path,options));
const rejected=assert.rejects(older,error=>error.name==='AbortError');
await auth.resolveBootstrap(async()=>({...principal,display_name:'更新姓名'}));const confirmed=auth.current();
release(new Response(JSON.stringify(principal)));await rejected;
assert.equal(auth.current(),confirmed);assert.equal(auth.current().display_name,'更新姓名');
""")
