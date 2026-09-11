import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path


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
 if(path==='/platform/device-bindings')return [{id:'b1',tenant_id:'t1',device_id:'d1',user_id:'u1',status:'active',is_default:true,auto_login_enabled:true,expires_at:null}];
 if(path==='/platform/tenants/t1/users')return [];throw new Error(path);
});
assert.deepEqual(paths.sort(),['/platform/device-bindings','/platform/tenants','/platform/tenants/t1/users']);
const html=center.render(model);assert.match(html,/new-tenant/);assert.match(html,/revoke-binding/);
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
