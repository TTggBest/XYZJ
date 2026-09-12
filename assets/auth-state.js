(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZhijuAuthState = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  let principal = null;
  let revision = 0;
  const listeners = new Set();
  const roles = { super_admin: "超级管理员", owner: "主账号所有者", admin: "主账号管理员", operator: "运营人员", viewer: "只读人员" };
  const managedRoles = ["admin", "operator", "viewer"];
  function current() { return principal; }
  function capture() { return revision; }
  function isCurrent(value) { return value === revision; }
  function subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); }
  function accept(value) { principal = value; revision += 1; listeners.forEach(listener => listener(value)); return value; }
  function clear() { accept(null); }
  function can(permission) { return Boolean(principal?.permissions?.includes(permission)); }
  function roleLabel(role) { return roles[role] || "未分配角色"; }
  function access() {
    const superAdmin = principal?.platform_role === "super_admin";
    const platform = superAdmin && principal?.device?.trust_level === "super_code_machine";
    const tenants = platform && can("platform.tenant.manage");
    const owner = principal?.membership_role === "owner" && Boolean(principal?.tenant_id);
    return {
      superAdmin, platform, switchTenant: superAdmin, tenants,
      users: tenants || (owner && can("user.read")),
      manageUsers: tenants || (owner && can("user.manage")),
      devices: platform && can("platform.device.manage"),
    };
  }
  function canManageUser(user) {
    return Boolean(user && !user.platform_role && access().manageUsers && (access().tenants || user.role_code !== "owner"));
  }
  function canChangeUserRole(user) { return canManageUser(user) && user.role_code !== "owner"; }
  function canView(view, deviceRole) {
    if (!principal) return false;
    if (view === "accounts") { const rights = access(); return rights.users || rights.tenants || rights.devices; }
    const permission = { settings: "platform.environment.manage", skills: "platform.environment.manage", logs: "audit.read" }[view];
    return permission ? deviceRole === "builder" && access().platform && can(permission) : Boolean(principal.tenant_id);
  }
  function usersPath(tenantId) {
    const rights = access();
    if (rights.tenants && tenantId) return `/platform/tenants/${encodeURIComponent(tenantId)}/users`;
    if (rights.users && (!tenantId || tenantId === principal.tenant_id)) return "/tenant/users";
    throw new Error("没有管理此主账号用户的权限");
  }
  function jsonOptions(body, method = "POST") { return { method, body: JSON.stringify(body) }; }
  async function resolveBootstrap(request) {
    const expectedRevision = capture();
    try { return accept(await request("/auth/me", { expectedRevision })); }
    catch (error) {
      if (error.name !== "AbortError" && error.status === 401) {
        // The shared request may have already cleared this revision on 401.
        if (isCurrent(expectedRevision)) clear();
        return null;
      }
      throw error;
    }
  }
  async function login(request, loginName, password) {
    return accept(await request("/auth/login", jsonOptions({ login_name: loginName.trim(), password })));
  }
  async function logout(request) {
    clear();
    return request("/auth/logout", { method: "POST" });
  }
  async function switchTenant(request, tenantId) {
    if (!access().switchTenant || !principal.switchable_tenants?.some(item => item.id === tenantId)) throw new Error("请选择有权限的主账号");
    clear();
    const expectedRevision = capture();
    try { return accept(await request("/auth/switch-tenant", { ...jsonOptions({ tenant_id: tenantId }), expectedRevision })); }
    catch (error) {
      if (!isCurrent(expectedRevision) || error.status === 401 || error.name === "AbortError") throw error;
      // A lost response can still mean the server switched the session. Never restore a cached actor.
      const confirmed = await request("/auth/me", { expectedRevision });
      accept(confirmed);
      if (confirmed.tenant_id !== tenantId) throw error;
      return confirmed;
    }
  }
  async function request(fetcher, path, options = {}) {
    const { expectedRevision: started = revision, ...fetchOptions } = options;
    if (!isCurrent(started)) throw new DOMException("账号上下文已改变", "AbortError");
    if (!principal && !path.startsWith("/auth/") && !path.startsWith("/api/v3/auth/")) throw Object.assign(new Error("请先登录"), { status: 401 });
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const response = await fetcher(path.startsWith("/api/") ? path : `/api/v3${path}`, {
      ...fetchOptions, credentials: "same-origin", cache: "no-store",
      headers: { ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
    });
    const text = await response.text();
    if (started !== revision) throw new DOMException("账号上下文已改变", "AbortError");
    let data = null;
    if (text) { try { data = JSON.parse(text); } catch { data = text; } }
    if (!response.ok) {
      if (response.status === 401) clear();
      const detail = typeof data?.detail === "string" ? data.detail : `请求失败（${response.status}）`;
      throw Object.assign(new Error(detail), { status: response.status });
    }
    return data;
  }
  return { current, capture, isCurrent, subscribe, clear, can, roleLabel, managedRoles, access, canManageUser, canChangeUserRole, canView, usersPath, resolveBootstrap, login, logout, switchTenant, request };
});
