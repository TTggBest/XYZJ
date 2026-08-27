(() => {
  "use strict";

  const API = "/api/v3";
  const NODE_TYPES = ["search", "title", "cover", "description", "community", "merge"];
  const NODE_LABELS = { search: "搜索", title: "标题", cover: "封面", description: "说明", community: "社群", merge: "合成" };
  const STATUS_LABELS = {
    active: "启用", new: "待配置", archived: "已归档", paused: "已暂停", authorized: "已授权", analyzed: "已分析", branded: "已装修", configured: "已配置", scheduled: "已排期",
    pending_dispatch: "待下发", dispatched: "已下发", running: "进行中", completed: "已完成", failed: "失败", cancelled: "已取消", pending: "待处理",
    reserved: "已预留", confirmed: "已确认", published: "已发布", draft: "草稿", ready: "已就绪", review_pending: "待审核", approved: "已通过",
    changes_requested: "需重做", delivered: "已交付", waiting: "等待中", in_progress: "进行中", succeeded: "已完成", skipped: "已跳过", retrying: "重试中",
    private: "私享", public: "公开", unlisted: "不公开", upload: "已上传", processed: "已处理", disabled: "停用", deprecated: "已弃用",
    missing: "缺失", partial: "部分就绪", expired: "已过期", blocked: "禁用", calibrated: "已校准",
    processing: "处理中", classified: "分类完成", partially_classified: "部分匹配", logo_ready: "Logo 已生成", partially_generated: "部分生成"
  };
  const VIEW_META = {
    dashboard: ["总览", "运营总览"], channels: ["频道", "频道管理"], dramas: ["剧库", "本地剧库"], schedules: ["排期", "频道排期"], publishSlots: ["排期", "频道档期表"], channelCadence: ["排期", "频道更新配置"],
    workorders: ["工单", "工单列表"], packages: ["运营包", "运营包列表"], youtube: ["YouTube", "YouTube 数据"],
    media: ["素材", "素材资产"], skills: ["Skills", "Skills 管理"], logs: ["系统日志", "状态与审计日志"], settings: ["设置", "系统设置"]
  };
  const state = { view: "dashboard", date: localDate(), dateManuallySet: false, channels: [], dramas: [], schedules: [], publishSlots: [], cadenceTemplates: [], tasks: [], workorders: [], packageItems: [], packageChannel: "", packageStatus: "", packageSearch: "", events: [], demo: null, copyValues: new Map(), logoProfiles: [], imageRuns: [], settingsTab: "cadence", realtimeSource: null, realtimeConnecting: false, realtimeRefreshTimer: null };
  const el = id => document.getElementById(id);
  const root = el("viewRoot");

  function localDate() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }
  function esc(value) {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
  }
  function fmt(value, dateOnly = false) {
    if (!value) return "—";
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return esc(value);
    return dateOnly ? date.toLocaleDateString("zh-CN") : date.toLocaleString("zh-CN", { hour12: false });
  }
  function fmtUtc(value, dateOnly = false) {
    if (!value) return "—";
    const text = String(value);
    const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : `${text}Z`;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return esc(value);
    const options = { timeZone: "Asia/Shanghai" };
    return dateOnly
      ? date.toLocaleDateString("zh-CN", options)
      : date.toLocaleString("zh-CN", { ...options, hour12: false });
  }
  function shortId(value) { return value ? `${String(value).slice(0, 8)}…` : "—"; }
  function label(value) { return STATUS_LABELS[value] || value || "—"; }
  function statusClass(value) {
    if (["active", "authorized", "completed", "succeeded", "approved", "published", "ready", "delivered", "confirmed", "calibrated", "classified", "logo_ready"].includes(value)) return "is-green";
    if (["failed", "cancelled", "blocked", "changes_requested", "expired"].includes(value)) return "is-red";
    if (["running", "in_progress", "dispatched", "review_pending", "retrying"].includes(value)) return "is-blue";
    if (["pending", "pending_dispatch", "reserved", "draft", "partial", "partially_classified", "partially_generated", "waiting"].includes(value)) return "is-amber";
    return "";
  }
  function tag(value) { return `<span class="tag ${statusClass(value)}">${esc(label(value))}</span>`; }
  function icon(name) { return `<i data-lucide="${name}"></i>`; }
  function renderIcons() { if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } }); }
  function query(params) {
    const search = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== "") search.set(key, value); });
    return search.toString() ? `?${search}` : "";
  }
  async function api(path, options = {}) {
    const isFormData = options.body instanceof FormData;
    const response = await fetch(path.startsWith("/api") ? path : `${API}${path}`, {
      ...options,
      headers: { ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) }
    });
    const text = await response.text();
    let data = null;
    if (text) { try { data = JSON.parse(text); } catch { data = text; } }
    if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `请求失败（${response.status}）`);
    return data;
  }
  function notify(message, isError = false) {
    const toast = document.createElement("div");
    toast.className = `toast${isError ? " is-error" : ""}`;
    toast.textContent = message;
    el("toastStack").appendChild(toast);
    setTimeout(() => toast.remove(), 3200);
  }
  function loading() { root.innerHTML = `<div class="loading"><div><div class="spinner"></div><p>正在读取数据库</p></div></div>`; }
  function empty(title, description, action = "", actionLabel = "") {
    return `<div class="empty-state"><div><div class="empty-icon">${icon("database")}</div><h3>${esc(title)}</h3><p>${esc(description)}</p>${action ? `<button class="button button-primary" data-action="${action}">${icon("plus")} ${esc(actionLabel)}</button>` : ""}</div></div>`;
  }
  function section(title, subtitle, body, actions = "") {
    return `<section class="section"><header class="section-head"><div class="section-title"><h2>${esc(title)}</h2>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>${actions}</header>${body}</section>`;
  }
  function table(headers, rows, minWidth = 760, wrapClass = "") {
    return `<div class="table-wrap ${wrapClass}"><table class="data-table" style="min-width:${minWidth}px"><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  }
  function progress(value) {
    const safe = Math.max(0, Math.min(100, Number(value || 0)));
    return `<div class="progress"><div class="progress-row"><span>总进度</span><strong>${safe}%</strong></div><div class="progress-track"><div class="progress-bar" style="width:${safe}%"></div></div></div>`;
  }
  function nodesStrip(nodes = {}) {
    return `<div class="node-strip" title="搜索 · 标题 · 封面 · 说明 · 社群 · 合成">${NODE_TYPES.map(type => {
      const status = nodes[type]?.status;
      const cls = ["completed", "succeeded"].includes(status) ? "is-done" : ["running", "in_progress"].includes(status) ? "is-active" : status === "failed" ? "is-failed" : "";
      return `<span class="node-dot ${cls}" title="${NODE_LABELS[type]}：${label(status)}"></span>`;
    }).join("")}</div>`;
  }
  function openModal(title, body) { el("modalTitle").textContent = title; el("modalBody").innerHTML = body; el("modalBackdrop").hidden = false; renderIcons(); }
  function closeModal() { el("modalBackdrop").hidden = true; }
  function openDrawer(title, body) { el("drawerTitle").textContent = title; el("drawerBody").innerHTML = body; el("drawerBackdrop").hidden = false; renderIcons(); }
  function closeDrawer() { el("drawerBackdrop").hidden = true; }
  function formData(form) { return Object.fromEntries(new FormData(form).entries()); }
  function idempotency(prefix, ...parts) { return `${prefix}:${parts.join(":")}:${Date.now()}`.slice(0, 160); }
  async function copyText(value) {
    if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
    const textarea = document.createElement("textarea"); textarea.value = value; textarea.style.position = "fixed"; textarea.style.opacity = "0"; document.body.appendChild(textarea); textarea.select(); document.execCommand("copy"); textarea.remove();
  }
  function readFileDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("图标文件读取失败"));
      reader.readAsDataURL(file);
    });
  }

  async function checkHealth() {
    try {
      const health = await api("/api/health");
      const ok = Boolean(health.ok && health.database?.ok);
      const production = health.environment === "production";
      const environmentState = el("environmentState");
      environmentState.hidden = false;
      environmentState.className = `environment-state ${production ? "is-production" : "is-development"}`;
      environmentState.textContent = production ? "生产环境" : "开发环境";
      el("dbState").innerHTML = `<span class="status-dot ${ok ? "is-ok" : "is-error"}"></span><span>${ok ? "MySQL 已连接" : "MySQL 异常"}</span>`;
      el("sideStatusDot").className = `status-dot ${ok ? "is-ok" : "is-error"}`;
      el("sideStatusText").textContent = ok ? "数据库已连接" : "数据库异常";
    } catch {
      el("dbState").innerHTML = `<span class="status-dot is-error"></span><span>服务不可用</span>`;
      el("sideStatusDot").className = "status-dot is-error";
      el("sideStatusText").textContent = "服务不可用";
    }
  }

  async function showDashboard() {
    const [channels, tasks, workorders, events] = await Promise.all([
      api("/channels/overview"), api(`/tasks/overview${query({ task_date: state.date })}`), api("/work-orders/overview"), api("/system-events?limit=8")
    ]);
    Object.assign(state, { channels, tasks, workorders, events });
    const todayOrders = workorders.filter(item => item.production_date === state.date);
    const pendingPackages = workorders.filter(item => ["review_pending", "changes_requested"].includes(item.package_status));
    const rows = todayOrders.slice(0, 8).map(item => `<tr><td><span class="cell-main">${esc(item.chinese_title)}</span><span class="cell-sub mono">${esc(item.business_drama_id)}</span></td><td>${esc(item.channel_name)}</td><td>${nodesStrip(item.nodes)}</td><td>${progress(item.progress_percent)}</td><td>${tag(item.work_order_status)}</td><td><button class="button button-secondary button-small" data-action="work-detail" data-id="${item.work_order_id}">${icon("arrow-right")} 详情</button></td></tr>`);
    const activity = events.length ? `<div class="section-body activity-list">${events.map(item => `<div class="activity"><div><strong>${esc(item.entity_type)} · ${esc(label(item.new_status))}</strong><p>${esc(item.reason)}<br>${fmtUtc(item.occurred_at)}</p></div></div>`).join("")}</div>` : empty("暂无系统动态", "数据库中尚无状态变更记录。", "", "");
    root.innerHTML = `<div class="page-stack">
      <div class="kpi-grid">
        ${kpi("radio-tower", "运营频道", channels.filter(x => !x.deleted_at).length, `${channels.filter(x => x.authorized_account_count > 0).length} 个已绑定授权`)}
        ${kpi("clipboard-list", "今日工单", tasks.length, `${tasks.filter(x => x.task_status === "pending_dispatch").length} 条待生产`)}
        ${kpi("list-checks", "进行中工单", todayOrders.filter(x => ["running", "dispatched"].includes(x.work_order_status)).length, `${todayOrders.length} 条当日工单`)}
        ${kpi("package-check", "待审核运营包", pendingPackages.length, "生产完成后统一审核")}
      </div>
      <div class="dashboard-grid">
        ${section("今日生产进度", `${state.date} · 搜索、标题、封面、说明、社群、合成`, rows.length ? table(["剧目", "频道", "节点", "进度", "状态", ""], rows, 850) : empty("今日还没有生产工单", "工单开始生产后，六个生产节点会在这里显示。", "go-workorders", "进入工单"), `<button class="button button-secondary button-small" data-action="go-workorders">查看全部 ${icon("arrow-right")}</button>`)}
        ${section("系统动态", "最近 8 条数据库状态事件", activity)}
      </div>
    </div>`;
  }
  function kpi(iconName, title, value, foot) { return `<article class="kpi"><div class="kpi-head"><span>${esc(title)}</span>${icon(iconName)}</div><div class="kpi-value">${Number(value || 0)}</div><div class="kpi-foot">${esc(foot)}</div></article>`; }

  async function showChannels() {
    const [channels, logoProfiles] = await Promise.all([api("/channels/overview"), api("/channels/logo-profiles")]);
    Object.assign(state, { channels, logoProfiles });
    const profileByChannel = new Map(logoProfiles.map(profile => [profile.channel_id, profile]));
    const rows = channels.map(item => { const profile = profileByChannel.get(item.channel_id); return `<tr><td><div class="identity-cell"><span class="avatar">${esc((item.display_name || "频").slice(0, 1))}</span><div><span class="cell-main">${esc(item.display_name)}</span><span class="cell-sub">${esc(item.original_name)}</span></div></div></td><td class="mono">${esc(item.youtube_channel_id)}</td><td>${esc(item.default_language || "—")}</td><td>${item.daily_publish_count}</td><td>${item.authorized_account_count ? tag("authorized") : tag("pending")}</td><td>${profile ? tag(profile.status) : tag("missing")}</td><td>${tag(item.status)}</td><td><div class="row-actions"><button class="button button-secondary button-small" data-action="configure-channel-logo" data-id="${item.channel_id}">${icon("image-up")} ${profile ? "更新 Logo" : "配置 Logo"}</button><button class="icon-button" title="查看频道" aria-label="查看频道" data-action="channel-detail" data-id="${item.channel_id}">${icon("arrow-right")}</button></div></td></tr>`; });
    root.innerHTML = `<div class="page-stack">${section("频道清单", `${channels.length} 个频道 · Logo 素材按频道独立保存`, rows.length ? table(["频道", "YouTube Channel ID", "语言", "日更", "授权", "Logo", "状态", ""], rows, 1060) : empty("还没有频道", "先录入频道，后续排期、任务和分析都以频道 ID 关联。", "add-channel", "新增频道"), `<button class="button button-primary" data-action="add-channel">${icon("plus")} 新增频道</button>`)}</div>`;
  }
  function channelLogoForm(channel) {
    return `<form class="form-grid" id="channelLogoForm"><input type="hidden" name="channel_id" value="${esc(channel.channel_id)}"><div class="field field-wide"><label>频道</label><input class="input" value="${esc(channel.display_name)}" disabled></div><div class="field"><label>左 Logo</label><input class="input" type="file" name="left_logo" accept="image/png,image/jpeg,image/webp" required></div><div class="field"><label>右 Logo</label><input class="input" type="file" name="right_logo" accept="image/png,image/jpeg,image/webp" required></div><div class="field field-wide"><label>tem 模板图</label><input class="input" type="file" name="template" accept="image/png,image/jpeg,image/webp" required></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">${icon("wand-sparkles")} 上传并自动校准</button></div></form>`;
  }
  function channelForm() {
    return `<form class="form-grid" id="channelForm"><div class="field field-wide"><label>原始频道名称</label><input class="input" name="original_name" required maxlength="255"></div><div class="field"><label>运营昵称</label><input class="input" name="operational_name" maxlength="255"></div><div class="field"><label>YouTube Channel ID</label><input class="input mono" name="youtube_channel_id" required maxlength="64"></div><div class="field"><label>目标国家/地区</label><input class="input" name="country_name_zh" required maxlength="120" placeholder="孟加拉国"></div><div class="field"><label>国家/地区代码</label><input class="input mono" name="country_code" required minlength="2" maxlength="2" placeholder="BD"></div><div class="field"><label>默认语言</label><input class="input" name="default_language" required placeholder="bn"></div><div class="field"><label>时区</label><input class="input mono" name="timezone" value="Asia/Shanghai" required></div><div class="field field-wide"><label>默认题材</label><input class="input" name="default_genre"></div><input type="hidden" name="daily_publish_count" value="0"><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存频道</button></div></form>`;
  }

  async function showDramas() {
    const dramas = await api("/dramas"); state.dramas = dramas;
    const rows = dramas.map(item => `<tr><td><span class="cell-main">${esc(item.chinese_title)}</span><span class="cell-sub">${esc(item.aliases.map(a => a.alias).join("、") || "无别名")}</span></td><td class="mono">${esc(item.drama_number)}</td><td><span class="cell-main">${esc(item.content_summary || "尚未录入剧情简介")}</span></td><td>${item.core_terms.length}</td><td>${tag(item.status)}</td><td><button class="button button-secondary button-small" data-action="drama-detail" data-id="${item.id}">查看</button></td></tr>`);
    root.innerHTML = `<div class="page-stack">${section("本地剧库", `${dramas.length} 部剧目 · 中文剧名完全匹配，别名独立维护`, rows.length ? table(["剧目", "剧库 ID", "剧情简介", "核心词", "状态", ""], rows, 850) : empty("剧库是空的", "录入中文剧名、别名、剧情与核心词，搜索节点会优先完全匹配剧库。", "add-drama", "录入剧目"), `<button class="button button-primary" data-action="add-drama">${icon("plus")} 录入剧目</button>`)}</div>`;
  }
  function dramaForm() {
    return `<form class="form-grid" id="dramaForm"><div class="field field-wide"><label>中文剧名</label><input class="input" name="chinese_title" required maxlength="255"></div><div class="field field-wide"><label>别名（使用逗号分隔）</label><input class="input" name="aliases" placeholder="别名一, 别名二"></div><div class="field field-wide"><label>剧情简介</label><textarea class="textarea" name="content_summary"></textarea></div><div class="field field-wide"><label>核心词（使用逗号分隔）</label><input class="input" name="core_terms" placeholder="逆袭, 豪门, 复仇"></div><div class="field field-wide"><label>资源地址</label><input class="input" name="baidu_cloud_url" type="url"></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存剧目</button></div></form>`;
  }

  async function showSchedules() {
    const [schedules, channels, dramas] = await Promise.all([api("/schedules/overview"), api("/channels/overview"), api("/dramas")]);
    Object.assign(state, { schedules, channels, dramas });
    const date = state.date;
    const filtered = schedules.filter(item => item.publish_date === date);
    const rows = filtered.map(item => `<tr><td>${esc(item.channel_name)}</td><td><span class="cell-main">${esc(item.chinese_title)}</span><span class="cell-sub">${esc(item.drama_code)}</span></td><td>${esc(item.slot_type === "main" ? "主档" : "辅档")} ${String(item.slot_local_time).slice(0, 5)}</td><td>${fmt(item.planned_beijing_time)}</td><td>${esc(item.playlist_name || "—")}</td><td>${item.community_count}</td><td>${tag(item.schedule_status)}</td><td><div class="row-actions">${item.task_id ? tag(item.task_status) : `<button class="button button-quiet button-small" data-action="create-task" data-id="${item.schedule_id}">生成工单</button>`}</div></td></tr>`);
    const tools = `<div class="toolbar"><div class="field"><label>排期日期</label><input class="input" type="date" id="scheduleDate" value="${date}"></div><button class="button button-secondary" data-action="go-publish-slots">${icon("clock-3")} 频道档期表</button><button class="button button-primary" data-action="add-schedule">${icon("plus")} 新建排期</button></div>`;
    root.innerHTML = `<div class="page-stack">${section("频道排期", `${filtered.length} 条当日安排 · 时间统一展示北京时间`, rows.length ? table(["频道", "剧目", "档位", "北京时间", "播放列表", "社群", "排期状态", "工单"], rows, 1040) : empty("当天没有排期", "选择频道、剧目和发布档位创建数据库排期。", "add-schedule", "新建排期"), tools)}</div>`;
  }
  function publishSlotItems(channel, slotType) {
    const slots = channel.slots.filter(item => item.slot_type === slotType);
    if (!slots.length) return `<span class="cell-sub">未设置</span>`;
    return `<div class="row-actions">${slots.map(slot => `<button class="button button-secondary button-small" data-action="edit-publish-slot" data-id="${slot.id}" data-channel-id="${channel.channel_id}">${slotType === "main" ? "主档" : "辅档"}${slot.slot_number} · ${String(slot.local_time).slice(0, 5)} · ${esc(label(slot.status))}</button>`).join("")}</div>`;
  }
  function dateTimeCell(date, timeValue) {
    return `<span class="cell-main mono">${esc(timeValue)}</span><span class="cell-sub">${esc(date)}</span>`;
  }
  function cadenceSlotStack(slots, render) {
    return `<div class="cadence-slot-stack">${slots.map((slot, index) => `<div class="cadence-slot-item${index ? " has-divider" : ""}">${render(slot)}</div>`).join("")}</div>`;
  }
  async function showPublishSlots() {
    const channels = await api(`/cadence-overview${query({ on_date: state.date })}`);
    state.publishSlots = channels;
    const rows = [];
    channels.forEach((channel, channelIndex) => {
      if (!channel.slots.length) {
        rows.push(`<tr><td class="serial-cell">${channelIndex + 1}</td><td><span class="cell-main">${esc(channel.display_name)}</span><span class="cell-sub">${esc(channel.youtube_channel_id)}</span></td><td><span class="cell-main">${esc(channel.country_name_zh || "未设置国家")}</span><span class="cell-sub">${esc(channel.default_language || "未设置语言")} · ${esc(channel.timezone)}</span></td><td>${[1, 2, 3, 4, 5].includes(channel.daily_publish_count) ? `${channel.daily_publish_count}更` : "未配置"}</td><td colspan="5"><span class="cell-sub">请先配置该频道每日几更</span></td></tr>`);
        return;
      }
      rows.push(`<tr><td class="serial-cell">${channelIndex + 1}</td><td><span class="cell-main">${esc(channel.display_name)}</span><span class="cell-sub">${esc(channel.youtube_channel_id)}</span></td><td><span class="cell-main">${esc(channel.country_name_zh || "未设置国家")}</span><span class="cell-sub">${esc(channel.default_language || "未设置语言")} · ${esc(channel.timezone)}</span></td><td>${channel.daily_publish_count}更</td><td>${cadenceSlotStack(channel.slots, slot => `<span class="tag ${slot.slot_type === "main" ? "is-green" : ""}">${slot.slot_type === "main" ? "主档" : "辅档"}</span><span class="cell-sub">档位 ${slot.slot_number}</span>`)}</td><td class="cadence-time-cell"><div class="cadence-time-box is-local">${cadenceSlotStack(channel.slots, slot => dateTimeCell(slot.local_video_date, slot.local_video_time))}</div></td><td class="cadence-time-cell"><div class="cadence-time-box is-beijing">${cadenceSlotStack(channel.slots, slot => dateTimeCell(slot.beijing_video_date, slot.beijing_video_time))}</div></td><td class="cadence-time-cell"><div class="cadence-time-box is-local">${cadenceSlotStack(channel.slots, slot => dateTimeCell(slot.local_engagement_date, slot.local_engagement_time))}</div></td><td class="cadence-time-cell"><div class="cadence-time-box is-beijing">${cadenceSlotStack(channel.slots, slot => dateTimeCell(slot.beijing_engagement_date, slot.beijing_engagement_time))}</div></td></tr>`);
    });
    const tools = `<div class="toolbar"><button class="button button-secondary" data-action="back-schedules">${icon("arrow-left")} 返回频道排期</button><div class="field"><label>展示日期</label><input class="input" type="date" id="cadenceDate" value="${state.date}"></div><button class="button button-primary" data-action="go-channel-cadence">${icon("sliders-horizontal")} 频道更新配置</button></div>`;
    root.innerHTML = `<div class="page-stack">${section("频道档期表", `${channels.length} 个频道 · 当地时间与北京时间按所选日期换算`, rows.length ? table(["序号", "频道", "国家 / 语言", "日更", "档位", "当地视频", "北京时间视频", "当地社群发布", "北京时间社群发布"], rows, 1320, "cadence-table-wrap") : empty("暂无频道", "请先录入频道，再配置每日更新时间。"), tools)}</div>`;
  }
  async function showChannelCadence() {
    const channels = await api("/channels/overview");
    state.channels = channels;
    const rows = channels.map((channel, index) => `<tr><td class="serial-cell">${index + 1}</td><td><span class="cell-main">${esc(channel.display_name)}</span><span class="cell-sub">${esc(channel.youtube_channel_id)}</span></td><td>${esc(channel.country_name_zh || "未设置")}</td><td><span class="cell-main">${esc(channel.default_language || "未设置")}</span></td><td class="mono">${esc(channel.timezone)}</td><td><select class="select cadence-count-select" id="cadence-count-${channel.channel_id}" aria-label="${esc(channel.display_name)}每日更新次数"><option value="">未配置</option>${[1,2,3,4,5].map(count => `<option value="${count}" ${channel.daily_publish_count === count ? "selected" : ""}>每日 ${count} 更</option>`).join("")}</select></td><td><button class="button button-primary button-small" data-action="save-channel-cadence" data-id="${channel.channel_id}">${icon("save")} 保存</button></td></tr>`);
    const tools = `<div class="row-actions"><button class="button button-secondary" data-action="go-publish-slots">${icon("clock-3")} 查看档期表</button></div>`;
    root.innerHTML = `<div class="page-stack">${section("频道更新配置", "国家、语言与时区读取频道资料，只配置每日更新次数", rows.length ? table(["序号", "频道", "国家 / 地区", "语言", "时区", "日更模板", ""], rows, 1050) : empty("暂无频道", "请先创建频道。"), tools)}</div>`;
  }
  function publishSlotForm(channel, slot = null) {
    return `<form class="form-grid" id="publishSlotForm"><input type="hidden" name="channel_id" value="${esc(channel.channel_id)}"><input type="hidden" name="publish_slot_id" value="${esc(slot?.id || "")}"><div class="field field-wide"><label>频道</label><input class="input" value="${esc(channel.display_name)}" disabled></div><div class="field"><label>档期类型</label><select class="select" name="slot_type" required><option value="main" ${slot?.slot_type === "main" ? "selected" : ""}>主档</option><option value="aux" ${slot?.slot_type === "aux" ? "selected" : ""}>辅档</option></select></div><div class="field"><label>同类档位编号</label><input class="input" type="number" name="slot_number" min="0" max="24" value="${slot?.slot_number ?? 1}" required></div><div class="field"><label>频道当地更新时间</label><input class="input" type="time" name="local_time" value="${slot ? String(slot.local_time).slice(0, 5) : "20:00"}" required></div><div class="field"><label>频道时区</label><input class="input mono" name="timezone" value="${esc(channel.timezone)}" readonly required></div><div class="field field-wide"><label>状态</label><select class="select" name="status"><option value="active" ${slot?.status !== "inactive" ? "selected" : ""}>启用</option><option value="inactive" ${slot?.status === "inactive" ? "selected" : ""}>停用</option></select></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存档期</button></div></form>`;
  }
  async function openScheduleForm() {
    if (!state.channels.length || !state.dramas.length) return notify("请先录入频道和剧目", true);
    openModal("新建频道排期", `<form class="form-grid" id="scheduleForm"><div class="field"><label>频道</label><select class="select" name="channel_id" id="scheduleChannel" required><option value="">选择频道</option>${state.channels.map(c => `<option value="${c.channel_id}">${esc(c.display_name)}</option>`).join("")}</select></div><div class="field"><label>剧目</label><select class="select" name="drama_id" required><option value="">选择剧目</option>${state.dramas.map(d => `<option value="${d.id}">${esc(d.chinese_title)}</option>`).join("")}</select></div><div class="field"><label>发布日期</label><input class="input" type="date" name="publish_date" value="${state.date}" required></div><div class="field"><label>发布档位</label><select class="select" name="publish_slot_id" id="scheduleSlot" required disabled><option value="">先选择频道</option></select></div><div class="field"><label>播放列表</label><select class="select" name="playlist_id" id="schedulePlaylist" disabled><option value="">不指定</option></select></div><div class="field"><label>社群数量</label><input class="input" type="number" name="community_count" value="0" min="0" max="20"></div><div class="field"><label>优先级</label><input class="input" type="number" name="priority" value="100" min="0"></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存排期</button></div></form>`);
  }
  async function loadChannelScheduling(channelId) {
    const [slots, playlists] = await Promise.all([api(`/channels/${channelId}/publish-slots`), api(`/channels/${channelId}/playlists`)]);
    const slot = el("scheduleSlot"), playlist = el("schedulePlaylist");
    slot.disabled = false; slot.innerHTML = `<option value="">选择档位</option>${slots.filter(x => x.status === "active").map(x => `<option value="${x.id}">${x.slot_type === "main" ? "主档" : "辅档"} ${String(x.local_time).slice(0, 5)} · ${esc(x.timezone)}</option>`).join("")}`;
    playlist.disabled = false; playlist.innerHTML = `<option value="">不指定</option>${playlists.filter(x => x.status === "active").map(x => `<option value="${x.id}">${esc(x.local_name)}</option>`).join("")}`;
  }

  async function showTasks() {
    const tasks = await api(`/tasks/overview${query({ task_date: state.date })}`); state.tasks = tasks;
    const rows = tasks.map(item => `<tr><td><input type="checkbox" class="task-check" value="${item.task_id}" ${item.task_status !== "pending_dispatch" ? "disabled" : ""}></td><td><span class="cell-main">${esc(item.chinese_title)}</span><span class="cell-sub">${esc(item.drama_code)}</span></td><td>${esc(item.channel_name)}</td><td>${fmt(item.planned_beijing_time)}</td><td>${item.community_count}</td><td>${tag(item.task_status)}</td><td>${item.work_order_id ? progress(item.progress_percent) : "—"}</td><td><div class="row-actions">${item.task_status === "pending_dispatch" ? `<button class="button button-primary button-small" data-action="dispatch-task" data-id="${item.task_id}">下发</button>` : item.work_order_id ? `<button class="button button-secondary button-small" data-action="work-detail" data-id="${item.work_order_id}">工单</button>` : ""}</div></td></tr>`);
    const tools = `<div class="toolbar"><div class="field"><label>任务日期</label><input class="input" type="date" id="taskDate" value="${state.date}"></div><button class="button button-secondary" data-action="dispatch-selected">下发选中</button><button class="button button-primary" data-action="dispatch-all">${icon("send")} 一键下发待下发</button></div>`;
    root.innerHTML = `<div class="page-stack">${section("数据库任务列表", `${tasks.length} 条任务 · 默认只下发状态为“待下发”的任务`, rows.length ? table(["", "剧目", "频道", "计划发布", "社群", "状态", "生产进度", ""], rows, 980) : empty("当天没有任务", "请先在排期页面为当天排期生成任务。", "go-schedules", "进入排期"), tools)}</div>`;
  }
  async function dispatchMany(ids) {
    if (!ids.length) return notify("没有待生产的工单", true);
    let done = 0;
    for (const id of ids) { try { await api(`/tasks/${id}/dispatch`, { method: "POST" }); done += 1; } catch (error) { notify(error.message, true); } }
    notify(`已开始生产 ${done} 条工单`); await loadView("workorders");
  }

  async function showWorkorders() {
    const tasks = await api(`/tasks/overview${query({ task_date: state.date })}`); state.tasks = tasks;
    const rows = tasks.map((item, index) => `<tr><td class="serial-cell">${index + 1}</td><td><input type="checkbox" class="task-check" value="${item.task_id}" ${item.task_status !== "pending_dispatch" ? "disabled" : ""}></td><td><span class="cell-main">${esc(item.chinese_title)}</span><span class="cell-sub mono">${esc(item.business_drama_id)}</span></td><td><span class="cell-main">${esc(item.channel_name)}</span><span class="cell-sub mono">${esc(item.batch_number || "未分批")}</span></td><td>${fmt(item.planned_beijing_time || item.target_publish_date)}</td><td>${item.community_count}</td><td>${tag(item.work_order_status || item.task_status)}</td><td>${item.work_order_id ? `${nodesStrip(item.nodes)}${progress(item.progress_percent)}` : `<span class="cell-sub">等待开始生产</span>`}</td><td><div class="row-actions">${item.task_status === "pending_dispatch" ? `<button class="button button-primary button-small" data-action="dispatch-task" data-id="${item.task_id}">${icon("play")} 开始生产</button>` : item.work_order_id ? `<button class="button button-secondary button-small" data-action="work-detail" data-id="${item.work_order_id}">查看进度</button>` : ""}</div></td></tr>`);
    const tools = `<div class="toolbar"><div class="field"><label>工单日期</label><input class="input" type="date" id="workDate" value="${state.date}"></div><button class="button button-secondary" data-action="sync-feishu-workorders">${icon("refresh-cw")} 一键同步飞书</button><button class="button button-secondary" data-action="dispatch-selected">开始生产选中</button><button class="button button-primary" data-action="dispatch-all">${icon("play")} 一键开始待生产</button><span class="stat-line">${tasks.length} 条工单</span></div>`;
    root.innerHTML = `<div class="page-stack">${section("工单列表", "罗列需要生产运营包的剧目，并显示搜索、标题、封面、说明、社群、合成进度", rows.length ? table(["序号", "", "剧目 / ID", "频道 / 批次", "计划发布", "社群", "状态", "生产进度", ""], rows, 1120) : empty("当天没有工单", "可从飞书同步，或先在排期页面生成工单。", "sync-feishu-workorders", "一键同步飞书"), tools)}</div>`;
  }
  async function workDetail(id) {
    const detail = await api(`/work-orders/${id}`);
    const w = detail.work_order, p = detail.package;
    openDrawer("工单详情", `<div class="detail-grid"><div class="detail-item"><span>工单状态</span><strong>${tag(w.status)}</strong></div><div class="detail-item"><span>运营包状态</span><strong>${tag(p.status)}</strong></div><div class="detail-item"><span>生产日期</span><strong>${fmt(w.production_date)}</strong></div><div class="detail-item"><span>目标发布日期</span><strong>${fmt(w.target_publish_date)}</strong></div></div><div class="detail-block"><h3>生产节点</h3>${table(["节点", "状态", "尝试", "执行器", "开始", "完成"], detail.nodes.map(n => `<tr><td>${esc(NODE_LABELS[n.node_type] || n.node_type)}</td><td>${tag(n.status)}</td><td>${n.attempt_number}</td><td>${esc(n.worker_key || "—")}</td><td>${fmtUtc(n.started_at)}</td><td>${fmtUtc(n.completed_at)}</td></tr>`), 620)}</div><div class="detail-block"><button class="button button-secondary" data-action="package-detail" data-id="${p.id}">${icon("package-open")} 查看运营包结果</button></div>`);
  }

  function copyKey(packageId, field, value) {
    if (!value) return "";
    const key = `${packageId}:${field}`;
    state.copyValues.set(key, String(value));
    return key;
  }
  function copyCell(labelText, packageId, field, value, note = "", className = "", progress = null) {
    const key = copyKey(packageId, field, value);
    const tracked = progress?.type && progress?.id;
    return `<button class="copy-cell ${className} ${progress?.copied ? "is-copy-complete" : ""}" type="button" data-action="copy-package-field" data-copy-key="${esc(key)}" ${tracked ? `data-package-id="${esc(packageId)}" data-output-type="${esc(progress.type)}" data-output-id="${esc(progress.id)}"` : ""} ${key ? "" : "disabled"}><span class="copy-cell-label">${esc(labelText)}</span>${note ? `<span class="copy-cell-value">${esc(note)}</span>` : ""}<span class="copy-hint">${icon(key ? "copy" : "minus")}</span></button>`;
  }
  function readCell(labelText, value, className = "") {
    return `<div class="read-cell ${className}"><span class="read-cell-label">${esc(labelText)}</span><div class="read-cell-value">${esc(value || "暂无内容")}</div></div>`;
  }
  function applyCopyProgress(progress) {
    const item = state.packageItems.find(row => row.package_id === progress.package_id);
    if (item) Object.assign(item, progress);
    document.querySelectorAll(".package-card").forEach(card => {
      if (card.dataset.packageId !== progress.package_id) return;
      card.classList.remove("copy-not_started", "copy-in_progress", "copy-completed");
      card.classList.add(`copy-${progress.copy_status}`);
    });
    const copied = new Set(progress.copied_keys || []);
    document.querySelectorAll("[data-output-type][data-output-id]").forEach(node => {
      if (node.dataset.packageId !== progress.package_id) return;
      node.classList.toggle("is-copy-complete", copied.has(`${node.dataset.outputType}:${node.dataset.outputId}`));
    });
  }
  function packageCard(item, index) {
    const sourceIncomplete = item.source_complete === false;
    const copiedKeys = new Set(item.copied_keys || []);
    const tracked = (type, id) => id ? { type, id, copied: copiedKeys.has(`${type}:${id}`) } : null;
    const titleMap = Object.fromEntries((item.titles || []).map(title => [title.variant_number, title]));
    const coverMap = new Map((item.covers || []).map(cover => [`${cover.title_id}:${cover.aspect_ratio}`, cover]));
    const titleCells = [1, 2, 3].map(number => {
      const title = titleMap[number];
      return `<div class="title-pair">${copyCell("原标题", item.package_id, `title-${number}`, title?.localized_title, title?.localized_title, "copy-cell-full", tracked("title", title?.id))}${readCell("标题翻译", title?.chinese_translation)}</div>`;
    }).join("");
    const coverCells = [1, 2, 3].map(number => {
      const title = titleMap[number];
      const cover45 = title ? coverMap.get(`${title.id}:4:5`) : null;
      const cover169 = title ? coverMap.get(`${title.id}:16:9`) : null;
      return `<div class="cover-pair"><strong>标题 ${number}<span>${esc(title?.core_phrase || "无核心词")}</span></strong>${copyCell("4:5", item.package_id, `cover-${number}-45`, cover45?.creative_prompt, "", "", tracked("cover", cover45?.id))}${copyCell("16:9", item.package_id, `cover-${number}-169`, cover169?.creative_prompt, "", "", tracked("cover", cover169?.id))}</div>`;
    }).join("");
    const description = item.description;
    const communityCells = (item.community_posts || []).map(post => `<div class="community-pair"><div class="community-schedule"><span>社群排期 ${post.sequence_number}</span><strong>${post.planned_time ? fmt(post.planned_time) : "待主副档规则"}</strong></div>${copyCell(`社群文案 ${post.sequence_number}`, item.package_id, `community-${post.sequence_number}`, post.localized_text, post.localized_text, "copy-cell-full", tracked("community_text", post.id))}${copyCell(`社群图 ${post.sequence_number}`, item.package_id, `community-image-${post.sequence_number}`, post.image_prompt, "", "", tracked("community_image", post.id))}</div>`).join("");
    const videoCell = item.youtube_video_id ? copyCell("Video ID", item.package_id, "video-id", item.youtube_video_id, item.youtube_video_id, "video-copy-cell") : "";
    const incompleteNote = sourceIncomplete ? `<span class="source-incomplete-note" title="${esc(item.source_incomplete_reason || "飞书源数据不完整")}">数据不完整</span>` : "";
    return `<article class="package-card copy-${esc(item.copy_status || "not_started")} ${sourceIncomplete ? "source-incomplete" : ""}" data-package-id="${item.package_id}" ${sourceIncomplete ? "inert aria-disabled=\"true\"" : ""}><header class="package-card-head"><span class="package-sequence">${index + 1}</span><div class="package-head-meta"><span class="channel-line">${esc(item.channel_name)}</span><span>档期 ${fmt(item.planned_local_time || item.target_publish_date)}</span><strong>${esc(item.chinese_title)}</strong><span class="mono">${esc(item.business_drama_id)}</span><span class="mono">${esc(item.batch_number || "未分批")}</span><span>v${item.package_version}</span></div><div class="package-card-actions">${incompleteNote}${tag(item.package_status)}${videoCell}<button class="icon-button detail-icon-button" title="查看完整详情" aria-label="查看完整详情" data-action="package-page-detail" data-id="${item.package_id}">${icon("maximize-2")}</button></div></header><div class="package-modules"><section class="package-module package-module-title"><h3>标题</h3><div class="title-list">${titleCells}</div></section><section class="package-module package-module-cover"><h3>封面提示词</h3><div class="cover-list">${coverCells}</div></section><section class="package-module package-module-text"><h3>说明与播放列表</h3>${readCell("播放列表", item.playlist_name, "playlist-read-cell")}<div class="description-pair">${copyCell("说明", item.package_id, "description", description?.localized_text, description?.localized_text, "copy-cell-full description-copy-cell", tracked("description", description?.id))}${readCell("说明翻译", description?.chinese_translation)}</div></section><section class="package-module package-module-community"><h3>社群</h3><div class="community-list">${communityCells || `<span class="module-empty">无需社群内容</span>`}</div></section></div></article>`;
  }
  async function showPackages() {
    state.copyValues.clear();
    const items = await api(`/packages/operations-overview${query({ production_date: state.date, status: state.packageStatus || null })}`); state.packageItems = items;
    const channels = [...new Map(items.map(item => [item.channel_id, item.channel_name])).entries()];
    const search = state.packageSearch.trim().toLowerCase();
    const filtered = items.filter(item => (!state.packageChannel || item.channel_id === state.packageChannel) && (!search || `${item.chinese_title} ${item.business_drama_id} ${item.batch_number || ""} ${item.channel_name}`.toLowerCase().includes(search)));
    const tools = `<div class="toolbar"><div class="field"><label>生产日期</label><input class="input" type="date" id="packageDate" value="${state.date}"></div><button class="button button-secondary" data-action="sync-feishu-packages">${icon("refresh-cw")} 一键同步飞书</button><div class="field"><label>频道</label><select class="select" id="packageChannel"><option value="">全部频道</option>${channels.map(([id, name]) => `<option value="${id}" ${state.packageChannel === id ? "selected" : ""}>${esc(name)}</option>`).join("")}</select></div><div class="field"><label>状态</label><select class="select" id="packageStatus"><option value="">全部状态</option>${["review_pending", "changes_requested", "approved", "delivered"].map(status => `<option value="${status}" ${state.packageStatus === status ? "selected" : ""}>${label(status)}</option>`).join("")}</select></div><div class="field search-field"><label>搜索</label><input class="input" id="packageSearch" value="${esc(state.packageSearch)}" placeholder="剧名、剧目 ID、批次、频道"></div></div>`;
    root.innerHTML = `<div class="page-stack">${section("运营包操作列表", `${filtered.length} 个运营包 · 点击带复制提示的内容即可复制`, filtered.length ? `<div class="package-list">${filtered.map(packageCard).join("")}</div>` : empty("没有匹配的运营包", "调整日期、频道、状态或搜索条件。"), tools)}</div>`;
  }
  function fullOutputField(title, value, packageId, field, copyable = true, progress = null) {
    const key = copyable ? copyKey(packageId, field, value) : "";
    const content = `<div class="full-output-head"><h3>${esc(title)}</h3>${copyable && key ? `<span class="copy-hint">${icon("copy")}</span>` : ""}</div><div class="full-output-body">${esc(value || "暂无内容")}</div>`;
    const tracked = progress?.type && progress?.id;
    return copyable ? `<button class="full-output full-output-copy ${progress?.copied ? "is-copy-complete" : ""}" type="button" data-action="copy-package-field" data-copy-key="${esc(key)}" ${tracked ? `data-package-id="${esc(packageId)}" data-output-type="${esc(progress.type)}" data-output-id="${esc(progress.id)}"` : ""} ${key ? "" : "disabled"}>${content}</button>` : `<section class="full-output">${content}</section>`;
  }
  async function showPackagePageDetail(id) {
    let item = state.packageItems.find(row => row.package_id === id);
    if (!item) item = (await api("/packages/operations-overview")).find(row => row.package_id === id);
    if (!item) throw new Error("运营包不存在");
    state.copyValues.clear();
    el("breadcrumbText").textContent = "运营包 / 详情"; el("pageTitle").textContent = item.chinese_title;
    const titleMap = Object.fromEntries((item.titles || []).map(title => [title.variant_number, title]));
    const coverMap = new Map((item.covers || []).map(cover => [`${cover.title_id}:${cover.aspect_ratio}`, cover]));
    const copiedKeys = new Set(item.copied_keys || []);
    const tracked = (type, outputId) => outputId ? { type, id: outputId, copied: copiedKeys.has(`${type}:${outputId}`) } : null;
    const titleGroups = [1, 2, 3].map(number => {
      const title = titleMap[number], cover45 = title ? coverMap.get(`${title.id}:4:5`) : null, cover169 = title ? coverMap.get(`${title.id}:16:9`) : null;
      return `<div class="detail-result-group"><h2>标题 ${number}${title?.core_phrase ? `<span>${esc(title.core_phrase)}</span>` : ""}</h2>${fullOutputField("标题", title?.localized_title, id, `detail-title-${number}`, true, tracked("title", title?.id))}${fullOutputField("标题翻译", title?.chinese_translation, id, `detail-title-translation-${number}`, false)}${fullOutputField("4:5 封面提示词", cover45?.creative_prompt, id, `detail-cover-${number}-45`, true, tracked("cover", cover45?.id))}${fullOutputField("16:9 封面提示词", cover169?.creative_prompt, id, `detail-cover-${number}-169`, true, tracked("cover", cover169?.id))}</div>`;
    }).join("");
    const community = (item.community_posts || []).map(post => `<div class="detail-result-group"><h2>社群 ${post.sequence_number}</h2>${fullOutputField("社群文案", post.localized_text, id, `detail-community-${post.sequence_number}`, true, tracked("community_text", post.id))}${fullOutputField("社群图提示词", post.image_prompt, id, `detail-community-image-${post.sequence_number}`, true, tracked("community_image", post.id))}</div>`).join("");
    root.innerHTML = `<div class="page-stack"><div class="detail-page-toolbar"><button class="button button-secondary" data-action="back-packages">${icon("arrow-left")} 返回运营包列表</button><div class="toolbar-spacer"></div>${tag(item.package_status)}</div><section class="package-summary"><div><span>频道</span><strong>${esc(item.channel_name)}</strong></div><div><span>Video ID</span><strong class="mono">${esc(item.youtube_video_id || "—")}</strong></div><div><span>档期</span><strong>${fmt(item.planned_local_time || item.target_publish_date)}</strong></div><div><span>播放列表</span><strong>${esc(item.playlist_name || "—")}</strong></div></section>${titleGroups}<div class="detail-result-group"><h2>说明与播放列表</h2>${fullOutputField("播放列表", item.playlist_name, id, "detail-playlist", false)}${fullOutputField("说明", item.description?.localized_text, id, "detail-description", true, tracked("description", item.description?.id))}${fullOutputField("说明翻译", item.description?.chinese_translation, id, "detail-description-translation", false)}${fullOutputField("置顶评论", item.description?.pinned_comment, id, "detail-pinned-comment")}</div>${community || `<div class="section">${empty("无需社群内容", "此运营包没有社群生产要求。")}</div>`}</div>`;
    renderIcons();
  }

  async function loadDemoStatus() {
    state.demo = await api("/demo-data/feishu-first20");
  }

  function injectDemoBar() {
    if (!state.demo.active || !state.demo.batch) return;
    const stack = root.querySelector(".page-stack");
    if (!stack) return;
    const batch = state.demo.batch, counts = state.demo.entity_counts || {};
    stack.insertAdjacentHTML("afterbegin", `<div class="demo-banner"><div class="demo-banner-copy"><strong>飞书前 20 条演示数据</strong><span>${fmt(batch.start_date)} 至 ${fmt(batch.end_date)} · ${batch.row_count} 条工单 · ${counts.channel || 0} 个频道 · ${counts.package || 0} 个运营包</span></div><div class="demo-banner-actions"><button class="button button-secondary button-small" data-action="view-demo-workorders">查看演示工单</button><button class="button button-danger button-small" data-action="delete-demo">一键删除演示数据</button></div></div>`);
  }

  async function showYoutube() {
    const [videos, comments, watermarks, quota] = await Promise.all([api("/youtube/videos"), api("/youtube/comments"), api("/youtube/sync-watermarks"), api("/youtube/quota-usage/summary")]);
    const videoRows = videos.map(v => `<tr><td><span class="cell-main">${esc(v.title || v.youtube_video_id)}</span><span class="cell-sub mono">${esc(v.youtube_video_id)}</span></td><td>${shortId(v.channel_id)}</td><td>${tag(v.publish_status)}</td><td>${tag(v.privacy_status)}</td><td>${fmt(v.scheduled_publish_at || v.published_at)}</td></tr>`);
    root.innerHTML = `<div class="page-stack"><div class="kpi-grid">${kpi("video", "视频", videos.length, "已落库 YouTube 视频")}${kpi("message-square", "评论", comments.length, "默认排除频道自身评论")}${kpi("refresh-cw", "同步水位", watermarks.length, "按频道和数据类型隔离")}${kpi("gauge", "配额记录", quota.length, "数据库聚合")}</div>${section("YouTube 视频", "数据读取自 MySQL，不读取 raw_json", videoRows.length ? table(["视频", "频道 ID", "发布状态", "隐私状态", "发布时间"], videoRows, 850) : empty("还没有 YouTube 视频数据", "频道授权并同步后，视频数据会按频道落库。"))}</div>`;
  }

  async function showMedia() {
    const [workspace, batches, runs, assets] = await Promise.all([api("/settings/image-workspace"), api("/image-processing/batches"), api("/image-processing/runs"), api("/media-assets")]);
    state.imageRuns = runs;
    const batchOptions = batches.map(batch => `<option value="${batch.id}">${esc(batch.batch_number)} · ${esc(batch.production_date)} · ${batch.package_count} 个运营包</option>`).join("");
    const importPanel = workspace ? `<form id="imageImportForm" class="image-import-panel"><div class="field"><label>生产批次</label><select class="select" name="batch_id" required><option value="">选择批次</option>${batchOptions}</select></div><div class="field"><label>选择文件夹</label><input class="input" type="file" name="folder_files" accept="image/*" webkitdirectory multiple></div><div class="field"><label>选择多张图片</label><input class="input" type="file" name="image_files" accept="image/*" multiple></div><button class="button button-primary" type="submit">${icon("folder-input")} 导入并分类</button></form>` : `<div class="workspace-required"><span>${icon("folder-cog")}</span><div><strong>请先配置图片根目录</strong><p>根目录配置后，系统才能保存频道素材和用户产物。</p></div><button class="button button-primary" data-action="go-image-settings">前往设置</button></div>`;
    const runRows = runs.map(run => `<tr><td><span class="cell-main mono">${esc(run.batch_number)}</span><span class="cell-sub">${fmtUtc(run.created_at)}</span></td><td>${tag(run.status)}</td><td>${run.total_files}</td><td>${run.matched_files}</td><td>${run.unmatched_files}</td><td>${run.generated_files}</td><td><div class="row-actions">${run.matched_files ? `<button class="button button-primary button-small" data-action="generate-run-logo" data-id="${run.id}">${icon("stamp")} 生成 Logo 图</button>` : ""}<button class="icon-button" title="查看处理明细" aria-label="查看处理明细" data-action="image-run-detail" data-id="${run.id}">${icon("list-tree")}</button></div></td></tr>`);
    const rows = assets.map(a => `<tr><td><span class="cell-main">${esc(a.original_filename || a.storage_key)}</span><span class="cell-sub mono">${esc(a.storage_key)}</span></td><td>${esc(a.asset_type)}</td><td>${esc(a.asset_role || "—")}</td><td>${esc(a.storage_provider)}</td><td>${tag(a.status)}</td><td>${fmtUtc(a.created_at)}</td></tr>`);
    root.innerHTML = `<div class="page-stack">${section("批次图片处理", workspace ? `${esc(workspace.resolved_root)} · 按批次、语言、频道、排期、剧名存储` : "尚未配置图片根目录", importPanel)}${section("处理历史", `${runs.length} 次导入记录`, runRows.length ? table(["批次", "状态", "导入", "已匹配", "未匹配", "Logo 成品", ""], runRows, 920) : empty("还没有处理记录", "选择生产批次和图片后开始导入。"))}${section("素材资产", `${assets.length} 项素材元数据 · 文件状态以数据库为准`, rows.length ? table(["素材", "类型", "用途", "存储", "状态", "创建时间"], rows, 900) : empty("还没有素材资产", "封面、社区图和文档产物生成后会登记到素材资产表。"))}</div>`;
  }

  async function showSkills() {
    const skills = await api("/skills");
    const rows = skills.map(s => `<tr><td><span class="cell-main">${esc(s.name)}</span><span class="cell-sub mono">${esc(s.code)}</span></td><td>${esc(s.category)}</td><td><span class="cell-main">${esc(s.purpose)}</span></td><td>${tag(s.status)}</td><td>${fmtUtc(s.updated_at)}</td><td><button class="button button-secondary button-small" data-action="skill-detail" data-id="${s.id}">查看版本</button></td></tr>`);
    root.innerHTML = `<div class="page-stack">${section("Skills 管理", "业务规则正文与版本均存储在数据库；不直接读取外部工作流文件", rows.length ? table(["Skill", "分类", "用途", "状态", "更新时间", ""], rows, 900) : empty("还没有 Skills", "创建 Skill 后再维护中英文版本与发布状态。", "add-skill", "新建 Skill"), `<button class="button button-primary" data-action="add-skill">${icon("plus")} 新建 Skill</button>`)}</div>`;
  }
  function skillForm() { return `<form class="form-grid" id="skillForm"><div class="field"><label>代码</label><input class="input mono" name="code" pattern="[a-z0-9][a-z0-9_-]*" required placeholder="xy-title"></div><div class="field"><label>名称</label><input class="input" name="name" required></div><div class="field"><label>分类</label><input class="input" name="category" required placeholder="production"></div><div class="field"><label>状态</label><select class="select" name="status"><option value="active">启用</option><option value="disabled">停用</option></select></div><div class="field field-wide"><label>用途</label><textarea class="textarea" name="purpose" required></textarea></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">创建 Skill</button></div></form>`; }
  async function skillDetail(id) {
    const skill = await api(`/skills/${id}`), versions = await api(`/skills/${id}/versions`);
    const current = skill.current_version;
    openDrawer(skill.name, `<div class="detail-grid"><div class="detail-item"><span>代码</span><strong class="mono">${esc(skill.code)}</strong></div><div class="detail-item"><span>状态</span><strong>${tag(skill.status)}</strong></div><div class="detail-item"><span>分类</span><strong>${esc(skill.category)}</strong></div><div class="detail-item"><span>版本数量</span><strong>${versions.length}</strong></div></div><div class="detail-block"><h3>当前中文正文</h3><pre class="code-preview">${esc(current?.body_zh_cn || "尚未发布版本")}</pre></div><div class="detail-block"><h3>当前原文</h3><pre class="code-preview">${esc(current?.body_original || "尚未发布版本")}</pre></div>`);
  }

  async function showLogs() {
    const [events, audits] = await Promise.all([api("/system-events?limit=100"), api("/audit-events?limit=100")]);
    const body = `<div class="segmented"><button class="segment is-active" data-log-tab="status">状态事件 ${events.length}</button><button class="segment" data-log-tab="audit">审计事件 ${audits.length}</button></div><div id="logTable" data-events='${esc(JSON.stringify(events))}' data-audits='${esc(JSON.stringify(audits))}'>${logTable(events, "status")}</div>`;
    root.innerHTML = `<div class="page-stack">${section("系统与审计日志", "所有状态流转、操作审计均读取数据库", `<div class="section-body">${body}</div>`)}</div>`;
  }
  function logTable(items, type) {
    const rows = items.map(item => type === "status" ? `<tr><td>${fmtUtc(item.occurred_at)}</td><td>${esc(item.entity_type)}</td><td class="mono">${shortId(item.entity_id)}</td><td>${tag(item.new_status)}</td><td>${esc(item.reason)}</td><td>${esc(item.actor_type)}</td></tr>` : `<tr><td>${fmtUtc(item.occurred_at)}</td><td>${esc(item.action)}</td><td>${esc(item.entity_type)}</td><td class="mono">${shortId(item.entity_id)}</td><td>${esc(item.change_summary || "—")}</td><td>${esc(item.actor_type)}</td></tr>`);
    return items.length ? table(type === "status" ? ["时间", "实体", "实体 ID", "新状态", "原因", "执行者"] : ["时间", "动作", "实体", "实体 ID", "变更摘要", "执行者"], rows, 900) : empty("暂无日志", "数据库中尚无对应记录。");
  }

  const SETTINGS_TABS = [["cadence", "档期配置", "clock-3"], ["images", "图片目录", "folder-cog"], ["runtime", "运行环境", "server-cog"], ["devices", "设备管理", "monitor-cog"], ["packages", "运行包打包", "package-plus"], ["credentials", "第三方凭证", "key-round"]];
  function settingsLayout(body) {
    const tabs = SETTINGS_TABS.map(([key, name, iconName]) => `<button class="settings-tab ${state.settingsTab === key ? "is-active" : ""}" data-settings-tab="${key}">${icon(iconName)}<span>${name}</span></button>`).join("");
    return `<div class="settings-layout"><aside class="settings-tabs">${tabs}</aside><div class="settings-content">${body}</div></div>`;
  }
  function settingValue(name, value, mono = false) {
    return `<div class="setting-value"><span>${esc(name)}</span><strong class="${mono ? "mono" : ""}">${esc(value ?? "—")}</strong></div>`;
  }
  function deviceForm(device = {}) {
    const value = (key, fallback = "") => esc(device[key] ?? fallback);
    return `<form class="form-grid" id="deviceForm"><div class="field"><label>设备标识</label><input class="input mono" name="device_key" required maxlength="120" value="${value("device_key")}" placeholder="fleet:m4-2"></div><div class="field"><label>显示名称</label><input class="input" name="name" required maxlength="120" value="${value("name")}"></div><div class="field"><label>运营别名</label><input class="input" name="alias" maxlength="120" value="${value("alias")}"></div><div class="field"><label>Hostname</label><input class="input mono" name="hostname" required maxlength="255" value="${value("hostname")}" placeholder="M4-2.local"></div><div class="field"><label>设备角色</label><select class="select" name="device_role"><option value="builder" ${device.device_role === "builder" ? "selected" : ""}>代码机</option><option value="studio" ${device.device_role === "studio" ? "selected" : ""}>Studio</option><option value="worker" ${!device.device_role || device.device_role === "worker" ? "selected" : ""}>生产设备</option></select></div><div class="field"><label>状态</label><select class="select" name="status"><option value="active" ${!device.status || device.status === "active" ? "selected" : ""}>启用</option><option value="inactive" ${device.status === "inactive" ? "selected" : ""}>停用</option><option value="retired" ${device.status === "retired" ? "selected" : ""}>退役</option></select></div><div class="field"><label>登录用户</label><input class="input mono" name="login_user" maxlength="120" value="${value("login_user")}"></div><div class="field"><label>操作系统</label><input class="input" name="os_type" required maxlength="40" value="${value("os_type", "macOS")}"></div><div class="field"><label>雷电地址</label><input class="input mono" name="thunderbolt_address" maxlength="45" value="${value("thunderbolt_address")}"></div><div class="field"><label>局域网地址</label><input class="input mono" name="lan_address" maxlength="45" value="${value("lan_address")}"></div><div class="field field-wide"><label>SSH 密钥路径</label><input class="input mono" name="ssh_key_path" maxlength="500" value="${value("ssh_key_path")}"></div><div class="field field-wide"><label>设备用途</label><input class="input" name="purpose" maxlength="255" value="${value("purpose")}"></div><input type="hidden" name="ip_address" value="${value("ip_address")}"><input type="hidden" name="ssh_address" value="${value("ssh_address")}"><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存设备</button></div></form>`;
  }
  function cadenceTemplateForm(template) {
    const count = template.daily_publish_count;
    const slots = [...template.slots].sort((a, b) => a.slot_number - b.slot_number);
    return `<form class="cadence-template-form" data-cadence-count="${count}"><header><div><h3>每日 ${count} 更</h3><span>当地视频发布时间</span></div><button class="button button-primary button-small" type="submit">${icon("save")} 保存</button></header><div class="cadence-template-slots">${slots.map(slot => `<div class="cadence-template-slot"><strong>档位 ${slot.slot_number}</strong><div class="field"><label>视频时间</label><input class="input" type="time" name="slot_${slot.slot_number}_time" value="${String(slot.local_video_time).slice(0, 5)}" required></div><div class="field"><label>档位类型</label><select class="select" name="slot_${slot.slot_number}_type"><option value="aux" ${slot.slot_type === "aux" ? "selected" : ""}>辅档</option><option value="main" ${slot.slot_type === "main" ? "selected" : ""}>主档</option></select></div><div class="field"><label>社群发布延迟</label><div class="input-suffix"><input class="input" type="number" name="slot_${slot.slot_number}_offset" value="${slot.engagement_offset_minutes}" min="0" max="1440" required><span>分钟</span></div></div></div>`).join("")}</div></form>`;
  }
  async function showSettings() {
    let body;
    if (state.settingsTab === "cadence") {
      const templates = await api("/cadence-templates");
      state.cadenceTemplates = templates;
      body = `<header class="settings-content-head"><div><h2>档期配置</h2><p>统一维护1更至5更的当地视频时间、主辅档及社群发布间隔；单更仅使用主档。</p></div></header><div class="cadence-template-list">${templates.map(cadenceTemplateForm).join("")}</div>`;
    } else if (state.settingsTab === "images") {
      const workspace = await api("/settings/image-workspace");
      body = `<header class="settings-content-head"><div><h2>图片目录</h2><p>相对路径以当前设备 ZHJ_SHARED_ROOT 为根；绝对路径只用于本机独立目录。</p></div></header><form id="imageWorkspaceForm" class="workspace-settings-form"><div class="field"><label>根目录</label><input class="input mono" name="root_path" value="${esc(workspace?.root_path || "images")}" required maxlength="1000"></div><button class="button button-primary" type="submit">${icon("save")} 保存目录</button></form>${workspace ? `<div class="setting-grid">${settingValue("当前设备解析路径", workspace.resolved_root, true)}${settingValue("系统素材（不随产物清理）", workspace.persistent_root, true)}${settingValue("用户产物（可重新生成）", workspace.output_root, true)}</div>` : ""}`;
    } else if (state.settingsTab === "runtime") {
      const data = await api("/settings/runtime");
      const environmentSwitch = data.can_switch_environment ? `<section class="environment-switch-panel"><div><strong>数据库环境</strong><span>切换后立即影响后续读取和写入；重启开发服务后默认回到开发库。</span></div><div class="environment-segmented" role="group" aria-label="数据库环境"><button class="environment-segment ${data.environment === "development" ? "is-active" : ""}" data-action="switch-database-environment" data-environment="development" ${data.environment === "development" ? "disabled" : ""}>开发环境</button><button class="environment-segment ${data.environment === "production" ? "is-active is-production" : ""}" data-action="switch-database-environment" data-environment="production" ${data.environment === "production" ? "disabled" : ""}>生产环境</button></div></section>` : "";
      body = `<header class="settings-content-head"><div><h2>运行环境</h2><p>当前进程、数据库和本机运行信息，只展示真实运行状态。</p></div>${tag(data.database_ok ? "active" : "failed")}</header>${environmentSwitch}<div class="setting-grid">${settingValue("系统", `${data.system} ${data.version}`)}${settingValue("当前数据库环境", data.environment === "production" ? "生产环境" : "开发环境")}${settingValue("启动模式", data.base_environment)}${settingValue("设备角色", data.device_role)}${settingValue("SSE 中心", data.realtime_hub_url, true)}${settingValue("Web 服务", `${data.host}:${data.port}`, true)}${settingValue("MySQL", `${data.database_host}:${data.database_port}/${data.database_name}`, true)}${settingValue("当前设备", data.hostname)}${settingValue("操作系统", data.operating_system)}${settingValue("处理器架构", data.architecture)}${settingValue("Python", data.python_version, true)}${settingValue("项目目录", data.project_root, true)}${settingValue("运营包产物目录", data.artifact_root, true)}</div>`;
    } else if (state.settingsTab === "devices") {
      const devices = await api("/devices");
      state.devices = devices;
      const rows = devices.map(device => `<tr><td><span class="cell-main">${esc(device.alias || device.name)}</span><span class="cell-sub mono">${esc(device.device_key)}</span></td><td><span class="cell-main mono">${esc(device.hostname)}</span><span class="cell-sub">${esc(device.login_user || "—")}</span></td><td>${tag(device.device_role)}</td><td><span class="cell-main mono">${esc(device.thunderbolt_address || "—")}</span><span class="cell-sub mono">${esc(device.lan_address || "—")}</span></td><td>${esc(device.purpose || "—")}</td><td>${tag(device.status)}</td><td>${fmtUtc(device.last_seen_at)}</td><td><button class="button button-secondary button-small" data-action="edit-device" data-id="${device.id}">编辑</button></td></tr>`);
      body = `<header class="settings-content-head"><div><h2>设备管理</h2><p>运行包按 hostname 自动识别本机，角色和网络地址以 MySQL 配置为准。</p></div><div class="row-actions"><button class="button button-secondary" data-action="register-current-device">${icon("monitor-up")} 登记当前设备</button><button class="button button-primary" data-action="add-device">${icon("plus")} 新增设备</button></div></header>${devices.length ? table(["设备", "主机名 / 用户", "角色", "雷电 / 局域网", "用途", "状态", "最后在线", ""], rows, 1120) : empty("还没有登记设备", "先新增设备，运行包才能在对应电脑上自动识别并启动。", "add-device", "新增设备")}`;
    } else if (state.settingsTab === "packages") {
      const [packages, appIcon] = await Promise.all([api("/runtime-packages"), api("/settings/app-icon")]);
      const currentPackage = packages[0];
      const rows = packages.map(item => {
        const download = item.id === currentPackage?.id && item.status === "succeeded"
          ? `<a class="button button-secondary button-small" href="/api/v3/runtime-packages/${encodeURIComponent(item.id)}/download">${icon("download")} 下载当前版本</a>`
          : `<span class="cell-sub">${item.status === "failed" ? esc(item.error_message || "构建失败") : "仅保留系统记录"}</span>`;
        return `<tr><td><span class="cell-main mono">${esc(item.version)}</span><span class="cell-sub">构建号 ${item.build_number}</span></td><td>${tag(item.status)}</td><td>${esc(item.target_environment)}</td><td>${item.file_count}</td><td>${item.size_bytes ? `${(item.size_bytes / 1048576).toFixed(2)} MB` : "—"}</td><td>${fmtUtc(item.completed_at || item.started_at)}</td><td>${download}</td></tr>`;
      });
      const iconPanel = `<section class="app-icon-panel"><img src="${esc(appIcon.preview_url)}" alt="当前智矩应用图标"><div class="app-icon-copy"><h3>应用图标</h3><p>当前来源：${appIcon.source_type === "custom" ? "自定义上传" : "系统默认"} · 更新于 ${fmtUtc(appIcon.applied_at)}</p><p class="mono">${esc(appIcon.desktop_app_path)}</p><form id="appIconForm" class="app-icon-form"><input class="input" type="file" name="icon_file" accept="image/png,image/jpeg" required><button class="button button-primary" type="submit">${icon("upload")} 上传并应用</button><button class="button button-secondary" type="button" data-action="restore-default-icon">恢复默认图标</button></form><span class="settings-muted">请选择至少 512×512 的正方形 PNG 或 JPEG，最大 10 MB。系统会自动生成透明圆角、安全边距和桌面阴影。</span></div></section>`;
      body = `<header class="settings-content-head"><div><h2>运行包打包</h2><p>构建不含业务数据和密钥的仅代码生产运行包；所有运行包固定为 production。</p></div><button class="button button-primary" data-action="build-runtime-package">${icon("package-plus")} 构建生产运行包</button></header>${iconPanel}<div class="settings-subhead"><h3>构建历史</h3></div>${packages.length ? table(["版本", "状态", "目标环境", "文件", "大小", "完成时间", "下载"], rows, 980) : empty("还没有运行包", "点击构建后，只保留版本和构建结果记录。", "build-runtime-package", "构建生产运行包")}`;
    } else {
      const [integrations, googleAccounts, oauthGrants] = await Promise.all([api("/integrations"), api("/accounts"), api("/oauth-grants")]);
      const integrationCards = await Promise.all(integrations.map(async integration => {
        const accounts = await api(`/integrations/${integration.id}/accounts`);
        const accountCards = await Promise.all(accounts.map(async account => {
          const credentials = await api(`/integration-accounts/${account.id}/credentials`);
          const credentialRows = credentials.map(item => `<div class="credential-row"><div><strong>${esc(item.credential_type)}</strong><span class="mono">${esc(item.secret_reference)}</span></div>${tag(item.status)}</div>`).join("");
          return `<div class="integration-account"><div class="integration-account-head"><div><strong>${esc(account.display_name)}</strong><span>${esc(account.external_account_id || account.account_key)}</span></div>${tag(account.status)}</div>${credentialRows || `<p class="settings-muted">尚未登记凭证引用</p>`}<button class="button button-secondary button-small" data-action="add-credential" data-id="${account.id}">${icon("key-round")} 添加凭证引用</button></div>`;
        }));
        return `<section class="integration-card"><header><div><h3>${esc(integration.name)}</h3><p>${esc(integration.provider_type)} · ${esc(integration.code)}</p></div>${tag(integration.status)}</header>${accountCards.join("") || `<p class="settings-muted">尚未绑定账号</p>`}<button class="button button-secondary button-small" data-action="add-integration-account" data-id="${integration.id}">${icon("user-plus")} 添加账号</button></section>`;
      }));
      const youtubeRows = googleAccounts.map(account => `<div class="credential-row"><div><strong>${esc(account.nickname)}</strong><span>${esc(account.google_email)} · ${oauthGrants.filter(grant => grant.account_id === account.id).length} 个授权</span></div>${tag(account.authorization_status)}</div>`).join("");
      body = `<header class="settings-content-head"><div><h2>第三方凭证</h2><p>统一管理外部服务账号与 Secret 引用，不保存或显示密钥明文。</p></div><button class="button button-primary" data-action="add-integration">${icon("plus")} 新增服务</button></header><div class="integration-grid"><section class="integration-card"><header><div><h3>YouTube OAuth</h3><p>Google 主账号与授权状态</p></div>${tag(googleAccounts.length ? "active" : "pending")}</header>${youtubeRows || `<p class="settings-muted">尚未登记 YouTube 授权账号</p>`}</section>${integrationCards.join("")}</div>`;
    }
    root.innerHTML = `<div class="page-stack">${settingsLayout(body)}</div>`;
  }
  function integrationForm() {
    return `<form class="form-grid" id="integrationForm"><div class="field"><label>服务代码</label><input class="input mono" name="code" required placeholder="feishu / telegram / deepseek"></div><div class="field"><label>服务名称</label><input class="input" name="name" required placeholder="飞书"></div><div class="field field-wide"><label>提供方类型</label><input class="input" name="provider_type" required placeholder="api / oauth / bot"></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存服务</button></div></form>`;
  }
  function integrationAccountForm(integrationId) {
    return `<form class="form-grid" id="integrationAccountForm"><input type="hidden" name="integration_id" value="${esc(integrationId)}"><div class="field"><label>账号稳定标识</label><input class="input mono" name="account_key" required></div><div class="field"><label>显示名称</label><input class="input" name="display_name" required></div><div class="field field-wide"><label>外部账号 ID</label><input class="input mono" name="external_account_id"></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存账号</button></div></form>`;
  }
  function credentialForm(accountId) {
    return `<form class="form-grid" id="credentialForm"><input type="hidden" name="account_id" value="${esc(accountId)}"><div class="field"><label>凭证类型</label><input class="input mono" name="credential_type" required placeholder="oauth / bot_token / api_key"></div><div class="field field-wide"><label>Secret 引用</label><input class="input mono" name="secret_reference" required placeholder="keychain://zhiju/feishu/main"></div><div class="form-actions"><button class="button button-secondary" type="button" data-close-modal>取消</button><button class="button button-primary" type="submit">保存引用</button></div></form>`;
  }

  const renderers = { dashboard: showDashboard, channels: showChannels, dramas: showDramas, schedules: showSchedules, publishSlots: showPublishSlots, channelCadence: showChannelCadence, workorders: showWorkorders, packages: showPackages, youtube: showYoutube, media: showMedia, skills: showSkills, logs: showLogs, settings: showSettings };
  function captureViewPosition() {
    const topbarBottom = document.querySelector(".topbar")?.getBoundingClientRect().bottom || 0;
    const anchor = [...document.querySelectorAll(".package-card")].find(card => card.getBoundingClientRect().bottom > topbarBottom);
    return {
      scrollY: window.scrollY,
      packageId: anchor?.dataset.packageId || "",
      anchorTop: anchor?.getBoundingClientRect().top ?? null,
    };
  }
  function restoreViewPosition(position) {
    if (!position) return;
    requestAnimationFrame(() => {
      const anchor = position.packageId
        ? document.querySelector(`.package-card[data-package-id="${CSS.escape(position.packageId)}"]`)
        : null;
      if (anchor && position.anchorTop !== null) {
        window.scrollBy({ top: anchor.getBoundingClientRect().top - position.anchorTop, behavior: "auto" });
      } else {
        window.scrollTo({ top: position.scrollY, behavior: "auto" });
      }
    });
  }
  async function loadView(view = state.view, options = {}) {
    const preservePosition = Boolean(options.preservePosition && view === state.view);
    const position = preservePosition ? captureViewPosition() : null;
    state.view = view;
    await loadDemoStatus();
    if (["schedules", "workorders", "packages"].includes(view) && state.demo.active && state.demo.batch && !state.dateManuallySet) state.date = state.demo.batch.start_date;
    const meta = VIEW_META[view] || VIEW_META.dashboard;
    el("breadcrumbText").textContent = meta[0]; el("pageTitle").textContent = meta[1];
    document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("is-active", item.dataset.view === view));
    el("appShell").classList.remove("mobile-nav-open");
    if (!preservePosition) { loading(); renderIcons(); }
    try {
      await renderers[view]();
      if (["dashboard", "schedules", "workorders", "packages"].includes(view)) injectDemoBar();
      renderIcons();
      restoreViewPosition(position);
    } catch (error) { root.innerHTML = `<div class="section">${empty("数据读取失败", error.message)}</div>`; renderIcons(); notify(error.message, true); }
  }

  function scheduleRealtimeRefresh() {
    clearTimeout(state.realtimeRefreshTimer);
    state.realtimeRefreshTimer = setTimeout(() => loadView(state.view, { preservePosition: true }), 250);
  }
  function closeRealtime() {
    if (state.realtimeSource) state.realtimeSource.close();
    state.realtimeSource = null;
  }
  async function connectRealtime() {
    if (document.visibilityState !== "visible" || state.realtimeConnecting || state.realtimeSource) return;
    state.realtimeConnecting = true;
    try {
      const config = await api("/realtime/config");
      if (document.visibilityState !== "visible") return;
      if (!config.enabled || !config.stream_url) return;
      const settingsNav = document.querySelector('[data-view="settings"]');
      if (settingsNav) settingsNav.hidden = config.device_role !== "builder";
      if (config.device_role !== "builder" && state.view === "settings") await loadView("dashboard");
      closeRealtime();
      const source = new EventSource(config.stream_url);
      let reconnecting = false;
      source.addEventListener("data.changed", scheduleRealtimeRefresh);
      source.addEventListener("open", () => {
        if (reconnecting) scheduleRealtimeRefresh();
        reconnecting = false;
      });
      source.addEventListener("error", () => { reconnecting = true; });
      state.realtimeSource = source;
    } catch (error) {
      console.warn("实时状态连接失败", error);
    } finally {
      state.realtimeConnecting = false;
    }
  }

  document.addEventListener("click", async event => {
    const closeModalButton = event.target.closest("[data-close-modal]"); if (closeModalButton) return closeModal();
    const closeDrawerButton = event.target.closest("[data-close-drawer]"); if (closeDrawerButton) return closeDrawer();
    const nav = event.target.closest("[data-view]"); if (nav) return loadView(nav.dataset.view);
    const settingsTab = event.target.closest("[data-settings-tab]");
    if (settingsTab) { state.settingsTab = settingsTab.dataset.settingsTab; return loadView("settings"); }
    const tab = event.target.closest("[data-log-tab]");
    if (tab) {
      document.querySelectorAll("[data-log-tab]").forEach(x => x.classList.toggle("is-active", x === tab));
      const box = el("logTable"), type = tab.dataset.logTab, items = JSON.parse(type === "status" ? box.dataset.events : box.dataset.audits); box.innerHTML = logTable(items, type); renderIcons(); return;
    }
    const button = event.target.closest("[data-action]"); if (!button) return;
    const action = button.dataset.action, id = button.dataset.id;
    try {
      if (action === "add-channel") openModal("新增频道", channelForm());
      else if (action === "configure-channel-logo") { const channel = state.channels.find(item => item.channel_id === id); if (channel) openModal("频道 Logo 配置", channelLogoForm(channel)); }
      else if (action === "add-drama") openModal("录入剧目", dramaForm());
      else if (action === "add-skill") openModal("新建 Skill", skillForm());
      else if (action === "add-schedule") await openScheduleForm();
      else if (action === "go-publish-slots") await loadView("publishSlots");
      else if (action === "go-channel-cadence") await loadView("channelCadence");
      else if (action === "save-channel-cadence") {
        const select = el(`cadence-count-${id}`);
        if (!select?.value) throw new Error("请选择每日更新次数");
        await api(`/channels/${id}/cadence`, { method: "PATCH", body: JSON.stringify({ daily_publish_count: Number(select.value) }) });
        notify("频道更新配置已保存");
        await loadView("channelCadence");
      }
      else if (action === "back-schedules") await loadView("schedules");
      else if (action === "add-publish-slot") { const channel = state.publishSlots.find(item => item.channel_id === button.dataset.channelId); if (channel) openModal("新增频道档期", publishSlotForm(channel)); }
      else if (action === "edit-publish-slot") { const channel = state.publishSlots.find(item => item.channel_id === button.dataset.channelId); const slot = channel?.slots.find(item => item.id === id); if (channel && slot) openModal("编辑频道档期", publishSlotForm(channel, slot)); }
      else if (action === "create-task") { await api("/tasks", { method: "POST", body: JSON.stringify({ schedule_id: id, task_date: state.date, idempotency_key: idempotency("task", id, state.date) }) }); notify("工单已生成"); await loadView("schedules"); }
      else if (action === "dispatch-task") await dispatchMany([id]);
      else if (action === "dispatch-selected") await dispatchMany([...document.querySelectorAll(".task-check:checked")].map(x => x.value));
      else if (action === "dispatch-all") await dispatchMany(state.tasks.filter(x => x.task_status === "pending_dispatch").map(x => x.task_id));
      else if (action === "sync-feishu-workorders") {
        button.disabled = true;
        const result = await api("/feishu-sync/work-orders", { method: "POST" });
        if (result.latest_date) {
          state.date = result.latest_date;
          state.dateManuallySet = true;
        }
        notify(`飞书工单同步完成：新增 ${result.rows_inserted}，更新 ${result.rows_updated}`);
        await loadView("workorders");
      }
      else if (action === "sync-feishu-packages") {
        button.disabled = true;
        const result = await api("/feishu-sync/operation-packages", { method: "POST" });
        if (result.latest_date) {
          state.date = result.latest_date;
          state.dateManuallySet = true;
        }
        notify(`飞书运营包同步完成：新增 ${result.rows_inserted}，更新 ${result.rows_updated}，跳过 ${result.rows_skipped}`);
        await loadView("packages", { preservePosition: true });
      }
      else if (action === "work-detail") await workDetail(id);
      else if (action === "package-detail" || action === "package-page-detail") await showPackagePageDetail(id);
      else if (action === "back-packages") await loadView("packages");
      else if (action === "copy-package-field") {
        const value = state.copyValues.get(button.dataset.copyKey);
        if (!value) return;
        await copyText(value);
        if (button.dataset.outputType && button.dataset.outputId && button.dataset.packageId) {
          const copyProgress = await api(`/packages/${button.dataset.packageId}/copy-progress`, {
            method: "PUT",
            body: JSON.stringify({ output_type: button.dataset.outputType, output_id: button.dataset.outputId })
          });
          applyCopyProgress(copyProgress);
        } else {
          button.classList.add("is-copied");
          setTimeout(() => button.classList.remove("is-copied"), 900);
        }
      }
      else if (action === "approve-package") { await api(`/packages/${id}/review`, { method: "POST", body: JSON.stringify({ decision: "approved", note: "运营台审核通过" }) }); notify("运营包已通过审核"); await loadView("packages", { preservePosition: true }); }
      else if (action === "channel-detail") { const data = await api(`/channels/${id}`); openDrawer(data.channel?.operational_name || data.channel?.original_name || "频道详情", `<pre class="code-preview">${esc(JSON.stringify(data, null, 2))}</pre>`); }
      else if (action === "drama-detail") { const d = state.dramas.find(x => x.id === id); openDrawer(d?.chinese_title || "剧目详情", `<div class="detail-grid"><div class="detail-item"><span>剧库 ID</span><strong class="mono">${esc(d?.drama_number)}</strong></div><div class="detail-item"><span>状态</span><strong>${tag(d?.status)}</strong></div><div class="detail-item"><span>别名</span><strong>${esc(d?.aliases.map(a => a.alias).join("、") || "—")}</strong></div><div class="detail-item"><span>资源地址</span><strong>${esc(d?.baidu_cloud_url || "—")}</strong></div></div><div class="detail-block"><h3>剧情简介</h3><div class="detail-item"><strong>${esc(d?.content_summary || "尚未录入")}</strong></div></div><div class="detail-block"><h3>核心词</h3>${(d?.core_terms || []).map(t => `<span class="tag">${esc(t.term)}</span>`).join(" ") || "—"}</div>`); }
      else if (action === "skill-detail") await skillDetail(id);
      else if (action === "view-demo-workorders") { state.date = state.demo?.batch?.start_date || localDate(); state.dateManuallySet = false; await loadView("workorders"); }
      else if (action === "delete-demo") { if (window.confirm("确认删除飞书前 20 条演示数据？正式数据不会被删除。")) { await api("/demo-data/feishu-first20", { method: "DELETE" }); state.demo = null; state.date = localDate(); state.dateManuallySet = false; closeDrawer(); notify("演示数据已全部删除"); await loadView("dashboard"); } }
      else if (action === "go-tasks") await loadView("workorders");
      else if (action === "go-image-settings") { state.settingsTab = "images"; await loadView("settings"); }
      else if (action === "generate-run-logo") { button.disabled = true; const run = await api(`/image-processing/runs/${id}/generate-logo`, { method: "POST" }); notify(`已生成 ${run.generated_files} 张 Logo 图`); await loadView("media", { preservePosition: true }); }
      else if (action === "image-run-detail") {
        const run = state.imageRuns.find(item => item.id === id);
        if (run) {
          const rows = run.items.map(item => `<tr><td>${esc(item.original_filename)}</td><td>${tag(item.match_status)}</td><td>${esc(item.image_role || "—")}</td><td class="mono">${esc(item.output_path || item.stored_path)}</td><td>${esc(item.error_message || "—")}</td></tr>`);
          openDrawer(`${run.batch_number} 处理明细`, table(["原文件", "匹配", "图片位", "文件路径", "说明"], rows, 820));
        }
      }
      else if (action === "go-workorders") await loadView("workorders");
      else if (action === "go-schedules") await loadView("schedules");
      else if (action === "add-device") openModal("新增设备", deviceForm());
      else if (action === "edit-device") { const device = (state.devices || []).find(item => item.id === id); if (device) openModal("编辑设备", deviceForm(device)); }
      else if (action === "register-current-device") { await api("/devices/register-current", { method: "POST" }); notify("当前设备已登记"); await loadView("settings"); }
      else if (action === "switch-database-environment") {
        button.disabled = true;
        const environment = button.dataset.environment;
        await api("/settings/runtime/environment", { method: "PUT", body: JSON.stringify({ environment }) });
        notify(environment === "production" ? "已切换到生产数据库" : "已切换到开发数据库");
        await checkHealth();
        await loadView("settings");
      }
      else if (action === "build-runtime-package") { button.disabled = true; await api("/runtime-packages/build", { method: "POST" }); notify("运行包构建完成"); await loadView("settings"); }
      else if (action === "restore-default-icon") { await api("/settings/app-icon/restore-default", { method: "POST" }); notify("默认应用图标已恢复"); await loadView("settings"); }
      else if (action === "add-integration") openModal("新增第三方服务", integrationForm());
      else if (action === "add-integration-account") openModal("添加第三方账号", integrationAccountForm(id));
      else if (action === "add-credential") openModal("添加凭证引用", credentialForm(id));
    } catch (error) { notify(error.message, true); }
  });

  document.addEventListener("change", async event => {
    if (["scheduleDate", "cadenceDate", "taskDate", "workDate", "packageDate"].includes(event.target.id)) { state.date = event.target.value || localDate(); state.dateManuallySet = true; await loadView(state.view); }
    if (event.target.id === "packageChannel") { state.packageChannel = event.target.value; await loadView("packages"); }
    if (event.target.id === "packageStatus") { state.packageStatus = event.target.value; await loadView("packages"); }
    if (event.target.id === "packageSearch") { state.packageSearch = event.target.value; await loadView("packages"); }
    if (event.target.id === "scheduleChannel" && event.target.value) { try { await loadChannelScheduling(event.target.value); } catch (error) { notify(error.message, true); } }
  });
  document.addEventListener("submit", async event => {
    event.preventDefault(); const form = event.target; const data = formData(form);
    try {
      if (form.id === "channelForm") { data.daily_publish_count = Number(data.daily_publish_count); data.country_code = data.country_code.toUpperCase(); for (const key of ["operational_name", "default_genre"]) if (!data[key]) data[key] = null; await api("/channels", { method: "POST", body: JSON.stringify(data) }); notify("频道已保存"); closeModal(); await loadView("channels"); }
      if (form.id === "channelLogoForm") {
        const payload = new FormData();
        payload.append("left_logo", form.elements.left_logo.files[0]);
        payload.append("right_logo", form.elements.right_logo.files[0]);
        payload.append("template", form.elements.template.files[0]);
        await api(`/channels/${data.channel_id}/logo-profile`, { method: "PUT", body: payload });
        notify("Logo 素材已上传并自动校准"); closeModal(); await loadView("channels");
      }
      if (form.id === "imageWorkspaceForm") { await api("/settings/image-workspace", { method: "PUT", body: JSON.stringify({ root_path: data.root_path }) }); notify("图片目录已保存"); await loadView("settings"); }
      if (form.id === "imageImportForm") {
        const files = [...form.elements.folder_files.files, ...form.elements.image_files.files];
        if (!files.length) throw new Error("请选择文件夹或图片");
        const payload = new FormData(); payload.append("batch_id", data.batch_id);
        files.forEach(file => payload.append("files", file, file.name));
        const run = await api("/image-processing/import", { method: "POST", body: payload });
        notify(`分类完成：匹配 ${run.matched_files}，未匹配 ${run.unmatched_files}`); await loadView("media", { preservePosition: true });
      }
      if (form.matches(".cadence-template-form")) {
        const count = Number(form.dataset.cadenceCount), slots = [];
        for (let slotNumber = 1; slotNumber <= count; slotNumber += 1) slots.push({ slot_number: slotNumber, slot_type: data[`slot_${slotNumber}_type`], local_video_time: data[`slot_${slotNumber}_time`], engagement_offset_minutes: Number(data[`slot_${slotNumber}_offset`]) });
        await api(`/cadence-templates/${count}`, { method: "PUT", body: JSON.stringify({ slots }) });
        notify(`${count}更档期模板已保存`); await loadView("settings");
      }
      if (form.id === "dramaForm") { data.aliases = data.aliases.split(/[,，]/).map(x => x.trim()).filter(Boolean); data.core_terms = data.core_terms.split(/[,，]/).map((term, index) => ({ term_type: "keyword", term: term.trim(), weight: Math.max(.1, 1 - index * .1), source: "manual" })).filter(x => x.term); data.status = "active"; await api("/dramas", { method: "POST", body: JSON.stringify(data) }); notify("剧目已入库"); closeModal(); await loadView("dramas"); }
      if (form.id === "skillForm") { await api("/skills", { method: "POST", body: JSON.stringify(data) }); notify("Skill 已创建"); closeModal(); await loadView("skills"); }
      if (form.id === "scheduleForm") { const channelId = data.channel_id; delete data.channel_id; data.community_count = Number(data.community_count); data.priority = Number(data.priority); if (!data.playlist_id) data.playlist_id = null; data.idempotency_key = idempotency("schedule", channelId, data.drama_id, data.publish_date); await api(`/channels/${channelId}/schedules`, { method: "POST", body: JSON.stringify(data) }); notify("排期已保存"); closeModal(); state.date = data.publish_date; await loadView("schedules"); }
      if (form.id === "publishSlotForm") { const channelId = data.channel_id, slotId = data.publish_slot_id; delete data.channel_id; delete data.publish_slot_id; data.slot_number = Number(data.slot_number); const path = slotId ? `/channels/${channelId}/publish-slots/${slotId}` : `/channels/${channelId}/publish-slots`; await api(path, { method: slotId ? "PATCH" : "POST", body: JSON.stringify(data) }); notify("频道档期已保存"); closeModal(); await loadView("publishSlots"); }
      if (form.id === "integrationForm") { data.status = "active"; await api("/integrations", { method: "POST", body: JSON.stringify(data) }); notify("第三方服务已保存"); closeModal(); await loadView("settings"); }
      if (form.id === "integrationAccountForm") { const integrationId = data.integration_id; delete data.integration_id; data.status = "pending"; if (!data.external_account_id) data.external_account_id = null; await api(`/integrations/${integrationId}/accounts`, { method: "POST", body: JSON.stringify(data) }); notify("第三方账号已保存"); closeModal(); await loadView("settings"); }
      if (form.id === "credentialForm") { const accountId = data.account_id; delete data.account_id; data.status = "active"; await api(`/integration-accounts/${accountId}/credentials`, { method: "PUT", body: JSON.stringify(data) }); notify("凭证引用已保存"); closeModal(); await loadView("settings"); }
      if (form.id === "appIconForm") { const file = form.elements.icon_file.files[0]; if (!file) throw new Error("请选择图标文件"); const dataUrl = await readFileDataUrl(file); await api("/settings/app-icon", { method: "PUT", body: JSON.stringify({ filename: file.name, data_url: dataUrl }) }); notify("应用图标已更新"); await loadView("settings"); }
      if (form.id === "deviceForm") { for (const key of ["alias", "login_user", "thunderbolt_address", "lan_address", "ssh_key_path", "ip_address", "ssh_address", "purpose"]) if (!data[key]) data[key] = null; await api("/devices/register", { method: "PUT", body: JSON.stringify(data) }); notify("设备配置已保存"); closeModal(); await loadView("settings"); }
    } catch (error) { notify(error.message, true); }
  });

  el("sidebarToggle").addEventListener("click", () => { el("appShell").classList.toggle("is-collapsed"); localStorage.setItem("zhiju.nav.collapsed", el("appShell").classList.contains("is-collapsed") ? "1" : "0"); });
  el("mobileMenu").addEventListener("click", () => el("appShell").classList.toggle("mobile-nav-open"));
  el("refreshView").addEventListener("click", async () => { await checkHealth(); await loadView(state.view, { preservePosition: true }); });
  el("modalBackdrop").addEventListener("click", event => { if (event.target === el("modalBackdrop")) closeModal(); });
  el("drawerBackdrop").addEventListener("click", event => { if (event.target === el("drawerBackdrop")) closeDrawer(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") { closeModal(); closeDrawer(); el("appShell").classList.remove("mobile-nav-open"); } });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return closeRealtime();
    checkHealth();
    loadView(state.view, { preservePosition: true });
    connectRealtime();
  });
  window.addEventListener("pagehide", closeRealtime);

  if (localStorage.getItem("zhiju.nav.collapsed") === "1" && window.innerWidth > 760) el("appShell").classList.add("is-collapsed");
  checkHealth(); loadView("dashboard"); connectRealtime(); renderIcons();
})();
