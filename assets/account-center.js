(function (root, factory) {
  const api = factory(typeof module === "object" && module.exports ? require("./auth-state.js") : root.ZhijuAuthState);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZhijuAccountCenter = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (auth) {
  "use strict";

  const titles = { "new-tenant": "创建主账号和负责人", "edit-tenant": "编辑公司资料", "transfer-owner": "转交主账号负责人", "new-user": "创建子账号", "edit-user": "编辑用户", "reset-password": "重置用户密码", "revoke-binding": "撤销设备绑定" };
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const nullable = value => value?.trim() || null;
  const lease = value => value ? new Date(value).toISOString() : null;
  const time = value => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "继承主账号";
  const status = (value, expiresAt) => value === "active" ? (expiresAt && new Date(expiresAt) <= new Date() ? "已到期" : "启用") : value === "revoked" ? "已撤销" : "停用";
  const localTime = value => { if (!value) return ""; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
  const button = (action, text, id = "", danger = false) => `<button type="button" class="button button-${danger ? "danger" : "secondary"} button-small" data-account-action="${action}" data-id="${esc(id)}">${esc(text)}</button>`;
  const input = (name, title, value = "", type = "text", required = false, extra = "") => `<label class="field"><span>${esc(title)}</span><input class="input" name="${name}" type="${type}" value="${esc(value)}" ${required ? "required" : ""} ${extra}></label>`;
  const select = (name, title, values, selected) => `<label class="field"><span>${esc(title)}</span><select class="select" name="${name}" required>${values.map(([value, label]) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></label>`;
  const statusInput = (name, title, value) => select(name, title, [["active", "启用"], ["suspended", "停用"]], value || "active");
  const roleInput = (name, title, value) => select(name, title, auth.managedRoles.map(role => [role, auth.roleLabel(role)]), value || "operator");
  const grid = (headers, rows) => `<div class="table-wrap"><table class="data-table account-table"><thead><tr>${headers.map(item => `<th>${esc(item)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.join("") : `<tr><td colspan="${headers.length}">暂无记录</td></tr>`}</tbody></table></div>`;
  const section = (title, description, body, actions = "") => `<section class="section"><header class="section-head"><div class="section-title"><h2>${esc(title)}</h2><p>${esc(description)}</p></div><div class="account-row-actions">${actions}</div></header>${body}</section>`;

  async function load(request, selectedTenantId = "") {
    const rights = auth.access();
    if (!rights.users && !rights.devices && !rights.tenants) throw new Error("没有账号管理权限");
    const tenants = rights.tenants ? await request("/platform/tenants") : [auth.current().current_tenant].filter(Boolean);
    const tenantId = tenants.find(item => item.id === (selectedTenantId || auth.current().tenant_id))?.id || tenants[0]?.id || "";
    const [users, bindings] = await Promise.all([
      rights.users && tenantId ? request(auth.usersPath(tenantId)) : [],
      rights.devices ? request("/platform/device-bindings") : [],
    ]);
    return { tenants, tenantId, users, bindings };
  }

  function render(model) {
    const rights = auth.access();
    if (!rights.users && !rights.devices && !rights.tenants) return "";
    let content = "";
    if (rights.tenants) {
      const rows = model.tenants.map(item => `<tr><td><span class="cell-main">${esc(item.company_name)}</span><span class="cell-sub">${esc(item.short_name)}</span></td><td>${status(item.status, item.lease_expires_at)}</td><td>${esc(time(item.lease_expires_at))}</td><td>${esc(item.contact_name || "—")}<span class="cell-sub">${esc(item.contact_phone || "")}</span></td><td><div class="account-row-actions">${button("select-tenant", "管理用户", item.id)}${button("edit-tenant", "编辑公司", item.id)}</div></td></tr>`);
      content += section("主账号", "公司、负责人和租约", grid(["公司", "状态", "租约到期", "联系人", "操作"], rows), button("new-tenant", "创建主账号"));
    }
    if (rights.users && model.tenantId) {
      const company = model.tenants.find(item => item.id === model.tenantId);
      const rows = model.users.map(user => `<tr><td><span class="cell-main">${esc(user.display_name)}</span><span class="cell-sub">${esc(user.login_name)}</span></td><td>${esc(auth.roleLabel(user.role_code))}</td><td>${status(user.status, user.lease_expires_at)}<span class="cell-sub">成员关系：${status(user.membership_status)}</span></td><td>${esc(time(user.lease_expires_at))}</td><td><div class="account-row-actions">${auth.canManageUser(user) ? button("edit-user", "编辑", user.id) + button("reset-password", "重置密码", user.id) : "—"}</div></td></tr>`);
      content += section(`用户 · ${company?.company_name || "当前主账号"}`, "账号租约留空时继承主账号；停用或重置密码会撤销已有会话。", grid(["用户 / 登录名", "角色", "状态", "租约到期", "操作"], rows),
        (rights.manageUsers ? button("new-user", "创建子账号") : "") + (rights.tenants ? button("transfer-owner", "转交负责人", model.tenantId) : ""));
    }
    if (rights.devices) {
      const rows = model.bindings.map(binding => `<tr><td class="mono">${esc(binding.device_id)}</td><td>${esc(model.tenants.find(item => item.id === binding.tenant_id)?.company_name || binding.tenant_id)}</td><td>${esc(model.users.find(item => item.id === binding.user_id)?.display_name || binding.user_id)}</td><td>${status(binding.status)}</td><td>${binding.is_default ? "默认账号" : "非默认"}<span class="cell-sub">${binding.auto_login_enabled ? "免登录已启用" : "等待人工登录"}</span></td><td>${binding.expires_at ? esc(time(binding.expires_at)) : "随账号有效期"}</td><td>${binding.status !== "revoked" ? button("revoke-binding", "撤销绑定", binding.id, true) : "—"}</td></tr>`);
      content += section("设备绑定", "设备绑定需在超级代码机通过本地登记服务完成。", grid(["设备", "公司", "用户", "状态", "登录方式", "有效期", "操作"], rows));
    }
    return `<div class="page-stack account-center">${content}</div>`;
  }

  function form(action, model = {}, record = {}) {
    const rights = auth.access();
    let body = "";
    if (["new-tenant", "edit-tenant", "transfer-owner"].includes(action) && !rights.tenants) throw new Error("没有平台管理权限");
    if (action === "new-tenant" || action === "edit-tenant") {
      body = input("company_name", "公司全称", record.company_name, "text", true, 'maxlength="255"') + input("short_name", "主账号简称", record.short_name, "text", true, 'maxlength="120"') +
        statusInput("status", "主账号状态", record.status) + input("lease_expires_at", "主账号租约到期（本地时间）", localTime(record.lease_expires_at), "datetime-local", true) +
        input("contact_name", "联系人", record.contact_name, "text", false, 'maxlength="120"') + input("contact_phone", "联系电话", record.contact_phone, "tel", false, 'maxlength="40"') +
        input("plan_code", "套餐代码（可选）", record.plan_code, "text", false, 'maxlength="60"') + input("remark", "备注", record.remark);
      if (action === "edit-tenant") body += input("tenant_id", "", record.id, "hidden") + input("suspended_reason", "停用原因", record.suspended_reason, "text", false, 'maxlength="500"');
      else body += `<p class="field-wide account-form-note">同一步创建这家公司的负责人登录账号。</p>` +
        input("owner_display_name", "负责人姓名", "", "text", true, 'maxlength="120"') + input("owner_login_name", "负责人登录名", "", "text", true, 'autocomplete="off" maxlength="120"') +
        input("owner_password", "负责人初始密码", "", "password", true, 'autocomplete="new-password" maxlength="1024"') + input("owner_lease_expires_at", "负责人租约（可留空）", "", "datetime-local");
    } else if (action === "new-user" || action === "edit-user") {
      if (!rights.manageUsers || (action === "edit-user" && !auth.canManageUser(record))) throw new Error("没有管理此用户的权限");
      body = input("display_name", "姓名", record.display_name, "text", true, 'maxlength="120"') + input("login_name", "登录名", record.login_name, "text", true, 'autocomplete="off" maxlength="120"') +
        statusInput("status", "账号状态", record.status) + input("lease_expires_at", "用户租约（可留空，本地时间）", localTime(record.lease_expires_at), "datetime-local");
      if (action === "new-user") body += input("password", "初始密码", "", "password", true, 'autocomplete="new-password" maxlength="1024"') + roleInput("role_code", "角色", "operator");
      else {
        body += input("user_id", "", record.id, "hidden") + input("suspended_reason", "停用原因", "", "text", false, 'maxlength="500"');
        if (auth.canChangeUserRole(record)) body += roleInput("role_code", "角色", record.role_code) + statusInput("membership_status", "在此主账号中的状态", record.membership_status);
      }
    } else if (action === "reset-password") {
      if (!auth.canManageUser(record)) throw new Error("没有重置此用户密码的权限");
      body = `<p class="field-wide account-form-note">重置 ${esc(record.display_name)} 的密码后，该用户所有现有会话都会失效。</p>` + input("user_id", "", record.id, "hidden") + input("password", "新密码", "", "password", true, 'autocomplete="new-password" maxlength="1024"');
    } else if (action === "transfer-owner") {
      const targets = model.users.filter(user => auth.canChangeUserRole(user) && user.status === "active" && user.membership_status === "active" && (!user.lease_expires_at || new Date(user.lease_expires_at) > new Date()));
      if (!targets.length) throw new Error("请先创建一名启用且租约有效的子账号，再转交负责人");
      body = `<p class="field-wide account-form-note">新负责人将成为此主账号唯一所有者；原负责人按下方角色保留。</p>` + select("user_id", "新负责人", targets.map(user => [user.id, `${user.display_name} · ${user.login_name}`]), targets[0].id) + roleInput("previous_owner_role", "原负责人保留角色", "admin");
    } else if (action === "revoke-binding") {
      if (!rights.devices) throw new Error("没有设备管理权限");
      body = `<p class="field-wide account-form-note">撤销后将取消该设备的免登录资格，并撤销此绑定关联的会话。</p>` + input("binding_id", "", record.id, "hidden") + input("reason", "撤销原因", "", "text", false, 'maxlength="500"');
    } else throw new Error("不支持此账号操作");
    return `<form class="form-grid" id="accountAdminForm" data-account-form="${action}">${body}<p class="field-wide account-form-error" id="accountFormError" role="alert" hidden></p><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-${action === "revoke-binding" ? "danger" : "primary"}" type="submit">${action === "revoke-binding" ? "确认撤销" : "保存"}</button></div></form>`;
  }

  function command(action, values, model) {
    const rights = auth.access();
    let path, body, method = "POST";
    if (["new-tenant", "edit-tenant", "transfer-owner"].includes(action) && !rights.tenants) throw new Error("没有平台管理权限");
    if (action === "new-tenant" || action === "edit-tenant") {
      path = "/platform/tenants";
      body = { company_name: values.company_name.trim(), short_name: values.short_name.trim(), status: values.status, lease_expires_at: lease(values.lease_expires_at), contact_name: nullable(values.contact_name), contact_phone: nullable(values.contact_phone), plan_code: nullable(values.plan_code), remark: nullable(values.remark) };
      if (action === "new-tenant") body.owner = { display_name: values.owner_display_name.trim(), login_name: values.owner_login_name.trim(), password: values.owner_password, lease_expires_at: lease(values.owner_lease_expires_at) };
      else { path += `/${encodeURIComponent(values.tenant_id || model.tenantId)}`; method = "PATCH"; body.suspended_reason = nullable(values.suspended_reason); }
    } else if (["new-user", "edit-user", "reset-password"].includes(action)) {
      if (!rights.manageUsers) throw new Error("没有用户管理权限");
      path = auth.usersPath(model.tenantId);
      const user = model.users?.find(item => item.id === values.user_id);
      if (action !== "new-user" && !auth.canManageUser(user)) throw new Error("没有管理此用户的权限");
      if (action === "reset-password") { path += `/${encodeURIComponent(values.user_id)}/password`; body = { password: values.password }; }
      else {
        if (action === "new-user" || auth.canChangeUserRole(user)) {
          if (!auth.managedRoles.includes(values.role_code)) throw new Error("请选择有效的子账号角色");
        }
        body = { display_name: values.display_name.trim(), login_name: values.login_name.trim(), status: values.status, lease_expires_at: lease(values.lease_expires_at) };
        if (action === "new-user") Object.assign(body, { password: values.password, role_code: values.role_code });
        else {
          method = "PATCH"; path += `/${encodeURIComponent(values.user_id)}`; body.suspended_reason = nullable(values.suspended_reason);
          if (auth.canChangeUserRole(user)) Object.assign(body, { role_code: values.role_code, membership_status: values.membership_status });
          // Send only changed fields so owner role edits do not touch shared account profiles.
          if (Object.hasOwn(user, "lease_expires_at") && values.lease_expires_at === localTime(user.lease_expires_at)) delete body.lease_expires_at;
          for (const key of Object.keys(body)) if (Object.hasOwn(user, key) && user[key] === body[key]) delete body[key];
          if (!body.suspended_reason && Object.keys(body).every(key => ["role_code", "membership_status", "suspended_reason"].includes(key))) delete body.suspended_reason;
        }
      }
    } else if (action === "transfer-owner") {
      if (!auth.managedRoles.includes(values.previous_owner_role)) throw new Error("请选择有效的原负责人角色");
      path = `/platform/tenants/${encodeURIComponent(model.tenantId)}/owner`; body = { user_id: values.user_id, previous_owner_role: values.previous_owner_role };
    } else if (action === "revoke-binding") {
      if (!rights.devices) throw new Error("没有设备管理权限");
      path = `/platform/device-bindings/${encodeURIComponent(values.binding_id)}/revoke`; body = { reason: nullable(values.reason) };
    } else throw new Error("不支持此账号操作");
    return { path, options: { method, body: JSON.stringify(body) } };
  }
  return { titles, load, render, form, command };
});
