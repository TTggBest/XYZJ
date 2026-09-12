# Central SaaS Phase 1 Tenant Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不影响 `zhiju_prod` 的前提下，把现有身份基础扩展为中心 MySQL 的全业务租户隔离，使第二家公司加入后无法通过列表、主键、批量写、外部同步、SSE 或文件元数据读写第一家公司的数据。

**Architecture:** 浏览器只通过中心 Web/API 登录；`Principal.tenant_id` 是普通业务请求唯一可信租户来源。业务表按父子数据图增加 `tenant_id`，业务会话自动过滤并由显式 tenant repository 校验主键/批量写，MySQL 复合外键兜底。平台目录、平台管理与登录引导保持独立会话。AI 通用任务队列、对象存储实现、Mac Worker 和收费分别进入后续计划，本阶段只给这些边界预留明确接口，不提前实现。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MySQL/PyMySQL、原生 HTML/CSS/JavaScript、pytest/httpx。

**Spec:** `docs/superpowers/specs/2026-09-11-central-saas-ai-worker-platform-design.md`

## Global Constraints

- 开发和验收只允许连接 `zhiju_dev`；本计划任何步骤都不迁移、查询或写入 `zhiju_prod`。
- 在 Task 18 全部通过且用户另行明确授权之前，不合并 `dev`、不部署、不切换生产环境。
- Task 16 完成之前，不允许第二个真实公司写入业务数据；测试租户只用于自动化测试和 `zhiju_dev` 验收数据。
- 一旦真实第二租户产生业务数据，不得回滚到不带租户条件的旧应用；故障时停写并前向修复。
- `tenant_id` 不从普通请求 body/query/header 取值。超级管理员也先通过现有 `/auth/switch-tenant` 选择作用租户；跨租户查询只走 `/platform/*`。
- 客户访问设备继续使用 `devices` + `device_user_bindings`；它不是 AI Worker。Worker Registry、任务租约和 Codex 调度不进入本阶段。
- 大文件最终进入对象存储。本阶段只隔离文件元数据和所有路径解析入口，不把本机文件目录误当长期 SaaS 存储方案。
- 每次检查必须能发现一个具体失败。迁移检查发现孤儿、父链租户不一致或重复业务键时立即停止，不猜测归属。
- 每个任务独立提交；不得把所有迁移或所有 API 改造压成一个不可审阅提交。

### Data Scope Map

下列平台目录保持全局、不加 `tenant_id`：`languages`, `publish_cadence_template_slots`, `integrations`, `skills`, `skill_versions`, `runtime_package_builds`, `app_icon_settings`, `schema_comments`。

下列业务图必须租户化：

- 租户设置/集成：`channel_drama_types`, `image_workspace_settings`, `integration_accounts`, `integration_credentials`, `google_accounts`, `google_oauth_grants`, `google_oauth_grant_scopes`, `account_channel_authorizations`, `authorization_events`, `oauth_authorization_states`, `feishu_sync_runs`。
- 频道：`channels`, `channel_profiles`, `channel_initialization_drafts`, `channel_pinned_comment_templates`, `channel_branding_assets`, `channel_keywords`, `channel_analysis_reports`, `channel_analysis_topic_scores`, `channel_analysis_keyword_scores`, `channel_audience_profiles`, `channel_strategy_recommendations`, `channel_analysis_evidence`, `channel_dna_versions`, `channel_dna_signals`, `channel_logo_profiles`, `channel_playlists`, `channel_publish_slots`, `channel_community_slots`, `channel_schedule_entries`, `sync_watermarks`, `youtube_channel_daily_metrics`。
- 剧目/排期：`dramas`, `drama_aliases`, `drama_core_terms`, `drama_translations`, `drama_production_states`, `schedule_candidates`, `schedule_change_history`。
- 生产/运营包：`production_batches`, `operation_tasks`, `task_events`, `work_orders`, `operation_packages`, `package_output_copy_states`, `production_node_runs`, `package_titles`, `package_descriptions`, `package_cover_variants`, `package_community_posts`, `community_post_assets`, `package_playlist_assignments`, `package_creative_slots`, `package_artifacts`, `package_validation_results`, `package_similarity_checks`, `system_events`。
- 素材/图片：`media_assets`, `image_processing_runs`, `image_processing_items`。
- YouTube：`youtube_videos`, `youtube_video_playlist_memberships`, `youtube_playlist_order_history`, `youtube_video_status_history`, `youtube_comments`, `youtube_comment_replies`, `youtube_video_daily_metrics`, `youtube_analytics_breakdowns`, `api_request_logs`, `quota_usage_logs`。
- 演示/审计：`demo_data_batches`, `demo_data_entities`, `audit_events`。其中仅明确的平台审计事件允许 `tenant_id` 为空。

身份表 `tenants`, `app_users`, `tenant_memberships`, `permissions`, `role_permissions`, `auth_sessions`, `device_user_bindings`, `auth_events`, `devices` 保持现有职责；`devices` 是客户访问设备注册表，不直接归一个租户，授权关系由 `device_user_bindings` 表达。

---

## Task 1: 固化路由分类与迁移预检

**Files:**
- Create: `backend/zhiju/tenant_scope.py`
- Create: `backend/scripts/audit_tenant_isolation.py`
- Create: `backend/tests/test_tenant_route_inventory.py`
- Create: `backend/tests/test_tenant_preflight.py`

- [ ] **Step 1: 写失败测试，要求每个 `/api/v3` 路由只有一种边界分类**

```python
def test_every_api_route_has_exactly_one_scope(app):
    actual = {
        (method, route.path)
        for route in app.routes
        if route.path.startswith("/api/v3/")
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }
    classified = PUBLIC_ROUTES | TENANT_ROUTES | PLATFORM_ROUTES | INTERNAL_ROUTES
    assert actual == classified
    assert not pairwise_intersections(PUBLIC_ROUTES, TENANT_ROUTES, PLATFORM_ROUTES, INTERNAL_ROUTES)
```

运行：`uv run pytest backend/tests/test_tenant_route_inventory.py -q`

预期：FAIL，当前没有权威路由分类。

- [ ] **Step 2: 定义四类路由清单**

`backend/zhiju/tenant_scope.py` 以 `(HTTP method, path template)` 为键导出，避免同一路径的 GET/POST 被错误归为同一权限：

```python
RouteKey = tuple[str, str]
PUBLIC_ROUTES: frozenset[RouteKey]
TENANT_ROUTES: frozenset[RouteKey]
PLATFORM_ROUTES: frozenset[RouteKey]
INTERNAL_ROUTES: frozenset[RouteKey]
```

混合模块逐个按路由分类；不得用文件名推断整组权限。OAuth callback 放 `PUBLIC_ROUTES`，但注明必须靠一次性 state 恢复租户；`/events/publish` 放 `INTERNAL_ROUTES`。

- [ ] **Step 3: 写只读预检测试和脚本**

脚本从开发配置读取连接并要求 `--expect-database zhiju_dev`，只输出 JSON：Alembic heads、表计数、父链孤儿、已知唯一键重复、无法推导租户的行数。数据库名不匹配立即退出；禁止 UPDATE/INSERT/DELETE。

```python
def test_preflight_rejects_multiple_heads(report):
    report["alembic_heads"] = ["a", "b"]
    assert validate_preflight(report) == ["multiple_alembic_heads"]
```

- [ ] **Step 4: 验证**

运行：`uv run pytest backend/tests/test_tenant_route_inventory.py backend/tests/test_tenant_preflight.py -q`

预期：PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/zhiju/tenant_scope.py backend/scripts/audit_tenant_isolation.py backend/tests/test_tenant_route_inventory.py backend/tests/test_tenant_preflight.py
git commit -m "test: inventory tenant isolation boundaries"
```

## Task 2: 建立 TenantSession 和显式租户实体读取

**Files:**
- Modify: `backend/zhiju/models/base.py`
- Modify: `backend/zhiju/database.py`
- Modify: `backend/zhiju/auth_context.py`
- Create: `backend/zhiju/tenant_repository.py`
- Create: `backend/tests/test_tenant_session.py`

- [ ] **Step 1: 写跨租户读写失败测试**

覆盖：列表自动过滤、`require_tenant_entity` 对他租户 ID 返回 404、新对象自动写当前租户、显式写入其他租户被拒绝、批量 ID 有一个不属于当前租户则整批失败。

```python
with tenant_session(tenant_a) as session:
    assert session.scalars(select(OwnedFixture)).all() == [row_a]
    with pytest.raises(HTTPException) as exc:
        require_tenant_entity(session, OwnedFixture, row_b.id)
    assert exc.value.status_code == 404
```

运行：`uv run pytest backend/tests/test_tenant_session.py -q`

预期：FAIL。

- [ ] **Step 2: 增加基础接口**

实现 `TenantOwnedMixin.tenant_id`（迁移期 `String(36)`, indexed, nullable）、`open_tenant_session(principal)`、`get_tenant_db(principal=Depends(get_current_principal))`、`require_tenant_entity(session, model, entity_id, lock=False)` 和 `require_tenant_entities(session, model, entity_ids, lock=False)` 五个明确接口。

`get_db` 只用于认证解析、平台管理和引导；`get_tenant_db` 要求 `principal.tenant_id` 非空，并写入 `Session.info["tenant_id"]`、`user_id`、`permissions`。

`get_optional_principal`/`get_current_principal` 解析成功后把同一 principal 缓存在 `request.state.principal`，供成功写入后的 SSE 发布中间件读取；不得在中间件中凭请求参数重建租户。

- [ ] **Step 3: 加 SQLAlchemy 会话保护**

`do_orm_execute` 给 tenant-owned SELECT/ORM UPDATE/DELETE 注入当前租户条件；`before_flush` 自动填写新行并拒绝跨租户对象。保留显式 repository，因为 `Session.get`、原生 SQL 和多父关系仍需业务校验。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_tenant_session.py backend/tests/test_auth_context.py -q`

预期：PASS。

```bash
git add backend/zhiju/models/base.py backend/zhiju/database.py backend/zhiju/auth_context.py backend/zhiju/tenant_repository.py backend/tests/test_tenant_session.py
git commit -m "feat: add tenant scoped database sessions"
```

## Task 3: 默认租户和根实体 tenant_id 迁移

**Files:**
- Create: `backend/alembic/versions/b1d4e7f2a610_seed_default_tenant_and_scope_roots.py` (`down_revision = "a9c4e7b2d613"`)
- Modify: `backend/zhiju/models/identity.py`
- Modify: `backend/zhiju/models/channel_intelligence.py`
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/models/production.py`
- Modify: `backend/zhiju/models/integration.py`
- Modify: `backend/zhiju/models/settings.py`
- Modify: `backend/zhiju/models/demo.py`
- Modify: `backend/zhiju/models/youtube.py`
- Modify: `backend/zhiju/models/audit.py`
- Modify: `backend/tests/test_model_contract.py`
- Create: `backend/tests/test_tenant_root_migration.py`

- [ ] **Step 1: 写模型与迁移失败测试**

固定 `DEFAULT_EXISTING_TENANT_ID = "00000000-0000-4000-8000-000000000001"`，断言以下根表包含可空且有索引的 `tenant_id`：`channels`, `dramas`, `production_batches`, `google_accounts`, `integration_accounts`, `channel_drama_types`, `image_workspace_settings`, `demo_data_batches`, `feishu_sync_runs`, `media_assets`, `audit_events`, `system_events`, `api_request_logs`, `quota_usage_logs`。

- [ ] **Step 2: 实现幂等 seed 与根表回填**

迁移插入显示名“智矩现有业务”的固定 UUID 租户和稳定 permission code，不创建账号密码或设备 secret。根表加 nullable `tenant_id`、索引并回填旧行。downgrade 在存在业务引用时明确拒绝删除默认租户。

- [ ] **Step 3: 用 MySQL DDL 编译测试验证索引和外键命名**

运行：`uv run pytest backend/tests/test_model_contract.py backend/tests/test_tenant_root_migration.py -q`

预期：PASS；失败说明模型/迁移不一致，禁止进入子图迁移。

- [ ] **Step 4: 提交**

```bash
git add backend/alembic/versions backend/zhiju/models backend/tests/test_model_contract.py backend/tests/test_tenant_root_migration.py
git commit -m "feat: scope tenant root records"
```

## Task 4: 频道图迁移与频道服务隔离

**Files:**
- Create: `backend/alembic/versions/c2e5f8a3b721_scope_channel_graph.py` (`down_revision = "b1d4e7f2a610"`)
- Modify: `backend/zhiju/models/identity.py`
- Modify: `backend/zhiju/models/channel_intelligence.py`
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/models/settings.py`
- Modify: `backend/zhiju/models/youtube.py`
- Modify: `backend/zhiju/services/channel.py`
- Modify: `backend/zhiju/services/identity.py`
- Modify: `backend/zhiju/api/channel.py`
- Modify: `backend/zhiju/api/identity.py`
- Create: `backend/tests/test_channel_tenant_isolation.py`

- [ ] **Step 1: 写两租户频道图测试**

同名/同外部 ID 测试数据分别属于 A/B。覆盖列表、详情、更新、删除、分析报告、DNA、播放列表、排期入口和批量频道操作。A 使用 B 的 ID 一律 404，A 列表不出现 B。

- [ ] **Step 2: 迁移频道子图并验证父链**

给审计文档 2.1.D 除根 `channels` 外所有表加 nullable `tenant_id`。从 channel/report/DNA version/schedule entry 强父链回填；父链不一致时抛出错误并停止升级。

- [ ] **Step 3: API 改用 tenant dependency，服务替换裸主键读取**

所有租户频道路由使用 `Depends(get_tenant_db)`。`PUT /devices/register` 保持平台设备注册边界。批量删除频道先用 `require_tenant_entities` 验证全部 ID，事务内再执行；不得部分删除。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_channel_tenant_isolation.py backend/tests/test_channel_* backend/tests/test_authorization_contract.py -q`

预期：PASS。

```bash
git add backend/alembic/versions backend/zhiju/models backend/zhiju/services/channel.py backend/zhiju/services/identity.py backend/zhiju/api/channel.py backend/zhiju/api/identity.py backend/tests
git commit -m "feat: isolate channel data by tenant"
```

## Task 5: 剧库、排期与运营服务隔离

**Files:**
- Create: `backend/alembic/versions/d3f6a9b4c832_scope_drama_schedule_graph.py` (`down_revision = "c2e5f8a3b721"`)
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/services/drama_library.py`
- Modify: `backend/zhiju/services/drama_progress.py`
- Modify: `backend/zhiju/services/operations.py`
- Modify: `backend/zhiju/services/schedule_video.py`
- Modify: `backend/zhiju/api/drama_library.py`
- Modify: `backend/zhiju/api/drama_progress.py`
- Modify: `backend/zhiju/api/operations.py`
- Create: `backend/tests/test_drama_schedule_tenant_isolation.py`

- [ ] **Step 1: 写失败测试**

覆盖剧目列表/分页/别名/翻译/进度、频道播放列表与发布位、候选排期、排期创建修改。特别断言 A 不能把 B 的 drama 关联到 A 的 channel。

- [ ] **Step 2: 迁移并回填**

别名、术语、翻译、生产状态从 drama 继承；candidate/change history 从 schedule、drama、channel 强父链推导。任一关联父表租户不一致则停止迁移。

- [ ] **Step 3: 隔离服务和混合目录路由**

剧目/排期业务使用 tenant session。`languages` 和 `publish_cadence_template_slots` 保持平台共享：普通登录用户可读，只有平台权限可写。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_drama_schedule_tenant_isolation.py backend/tests/test_drama_* backend/tests/test_channel_schedule_* backend/tests/test_operations_contract.py -q`

```bash
git add backend/alembic/versions backend/zhiju/models/operations.py backend/zhiju/services backend/zhiju/api backend/tests
git commit -m "feat: isolate drama and schedule data by tenant"
```

## Task 6: 生产、工单和运营包隔离

**Files:**
- Create: `backend/alembic/versions/e4a7b0c5d943_scope_production_package_graph.py` (`down_revision = "d3f6a9b4c832"`)
- Modify: `backend/zhiju/models/production.py`
- Modify: `backend/zhiju/services/production.py`
- Modify: `backend/zhiju/services/package_outputs.py`
- Modify: `backend/zhiju/api/production.py`
- Create: `backend/tests/test_production_tenant_isolation.py`

- [ ] **Step 1: 写两租户生产链测试**

覆盖 `production_batches -> operation_tasks -> task_events/work_orders -> operation_packages -> package children/node runs`。A 不能按 B 的 task/work-order/package/node ID 读取、领取、开始、完成、重试、审核、复制或生成产物。

- [ ] **Step 2: 迁移并校验多父关系**

对 batch/channel/drama/schedule/package/media/playlist 多父关系逐行验证租户一致。发现一条 mismatch 就停止迁移并输出表名与内部行 ID，不自动选一个父表覆盖。

- [ ] **Step 3: 隔离服务**

节点开始/心跳/完成必须从 `production_node_runs.tenant_id` 恢复上下文；浏览器传入的 tenant 不参与判断。旧生产节点接口暂时属于内部受控边界，Phase 2 通用 Worker 计划再替换协议。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_production_tenant_isolation.py backend/tests/test_production_contract.py backend/tests/test_package_* -q`

```bash
git add backend/alembic/versions backend/zhiju/models/production.py backend/zhiju/services/production.py backend/zhiju/services/package_outputs.py backend/zhiju/api/production.py backend/tests
git commit -m "feat: isolate production packages by tenant"
```

## Task 7: 素材和图片处理隔离

**Files:**
- Create: `backend/alembic/versions/f5b8c1d6e054_scope_media_image_graph.py` (`down_revision = "e4a7b0c5d943"`)
- Modify: `backend/zhiju/models/settings.py`
- Modify: `backend/zhiju/models/channel_intelligence.py`
- Modify: `backend/zhiju/services/image_processing.py`
- Modify: `backend/zhiju/api/image_processing.py`
- Create: `backend/zhiju/storage_scope.py`
- Create: `backend/tests/test_image_tenant_isolation.py`
- Create: `backend/tests/test_storage_scope.py`

- [ ] **Step 1: 写跨租户文件入口失败测试**

覆盖素材列表、导入 run/items、未匹配文件、Logo、打开文件夹/文件下载元数据。A 即使知道 B 的 storage key、run ID 或 media ID 也返回 404。

- [ ] **Step 2: 迁移 image run/item 并隔离设置**

`image_processing_runs/items` 从 workspace/batch/media 强父链回填；`image_workspace_settings` 改为每租户一条逻辑配置。

- [ ] **Step 3: 收口路径解析**

实现 `tenant_object_prefix(tenant_id)` 返回 `tenants/{tenant_id}/`，并实现 `require_tenant_storage_key(tenant_id, key)`：前缀不属于当前租户时统一返回 404。

所有新写元数据要求 `tenants/<tenant_id>/...` 前缀；旧默认租户本地路径只通过单一 legacy adapter 读取，禁止其他租户进入。真正上传对象存储和保留期清理留给 Phase 3。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_image_tenant_isolation.py backend/tests/test_storage_scope.py backend/tests/test_image_processing_contract.py backend/tests/test_media_* -q`

```bash
git add backend/alembic/versions backend/zhiju/models backend/zhiju/services/image_processing.py backend/zhiju/api/image_processing.py backend/zhiju/storage_scope.py backend/tests
git commit -m "feat: isolate media processing by tenant"
```

## Task 8: Google、YouTube 与 OAuth 租户隔离

**Files:**
- Create: `backend/alembic/versions/a6c9d2e7f165_scope_oauth_youtube_graph.py` (`down_revision = "f5b8c1d6e054"`)
- Modify: `backend/zhiju/models/integration.py`
- Modify: `backend/zhiju/models/youtube.py`
- Modify: `backend/zhiju/services/youtube.py`
- Modify: `backend/zhiju/services/youtube_oauth.py`
- Modify: `backend/zhiju/services/youtube_channel_sync.py`
- Modify: `backend/zhiju/api/youtube.py`
- Modify: `backend/zhiju/api/youtube_oauth.py`
- Create: `backend/tests/test_youtube_tenant_isolation.py`
- Create: `backend/tests/test_oauth_tenant_state.py`

- [ ] **Step 1: 写 OAuth state 和 YouTube 图失败测试**

数据库表 `oauth_authorization_states` 中的 state 必须一次性绑定 `tenant_id + user_id + session_id + channel_id + expires_at + consumed_at`。callback 不接受 query 中另传 tenant。A 不能同步、评论、建播放列表或读 B 的 video/channel/grant。

- [ ] **Step 2: 迁移 grant/scope/authorization 和 YouTube 子图**

新增 `oauth_authorization_states` 并给 grant/scope/authorization 和 YouTube 子图增加租户归属；旧的进程内 pending state 不迁移。从 account/grant/channel/video 强父链回填。远程 YouTube channel/video 的全局唯一规则保留；其他租户授权相同远程资源时返回通用冲突，不泄露归属公司。

- [ ] **Step 3: 实现一次性 state 消费**

实现 `create_oauth_state(session, principal, channel_id) -> str` 和 `consume_oauth_state(session, opaque_state) -> OAuthTenantContext`。消费操作必须在事务中从“未消费”改为“已消费”，同一 state 第二次使用失败。

只有消费成功后才建立租户 session 并落授权结果。平台 OAuth client 密钥设置仍为平台接口。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_youtube_tenant_isolation.py backend/tests/test_oauth_tenant_state.py backend/tests/test_youtube_* backend/tests/test_authorization_contract.py -q`

```bash
git add backend/alembic/versions backend/zhiju/models backend/zhiju/services/youtube* backend/zhiju/api/youtube* backend/tests
git commit -m "feat: isolate youtube authorization by tenant"
```

## Task 9: 集成账号、飞书、智盒同步和演示数据隔离

**Files:**
- Create: `backend/alembic/versions/b7d0e3f8a276_scope_integration_sync_demo_graph.py` (`down_revision = "a6c9d2e7f165"`)
- Modify: `backend/zhiju/models/integration.py`
- Modify: `backend/zhiju/models/production.py`
- Modify: `backend/zhiju/models/demo.py`
- Modify: `backend/zhiju/services/integration.py`
- Modify: `backend/zhiju/services/feishu_sync.py`
- Modify: `backend/zhiju/services/zhihe_progress_sync.py`
- Modify: `backend/zhiju/services/demo.py`
- Modify: `backend/zhiju/api/integration.py`
- Modify: `backend/zhiju/api/feishu_sync.py`
- Modify: `backend/zhiju/api/demo.py`
- Create: `backend/tests/test_external_sync_tenant_isolation.py`

- [ ] **Step 1: 写失败测试**

同一个飞书 row key、集成账号名称和 demo batch 可在不同租户存在。A 的同步只能创建/更新 A 的频道、剧目、批次、任务和运营包；不能命中 B 的同名对象。

- [ ] **Step 2: 迁移与唯一键收口**

`integration_credentials.tenant_id` 只能继承 account；demo entity 继承 batch；同步 run 绑定租户。把租户内唯一业务键改成 `(tenant_id, business_key)`。

- [ ] **Step 3: 隔离混合接口**

`GET /integrations` 是已登录可读的平台目录；平台目录写要求平台权限；account/credential/sync 都使用 tenant session。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_external_sync_tenant_isolation.py backend/tests/test_feishu_* backend/tests/test_integration_contract.py backend/tests/test_demo_contract.py backend/tests/test_zhihe_progress_sync.py -q`

```bash
git add backend/alembic/versions backend/zhiju/services backend/zhiju/api backend/tests
git commit -m "feat: isolate external sync data by tenant"
```

## Task 10: 历史、审计与租户设置隔离

**Files:**
- Modify: `backend/zhiju/services/history.py`
- Modify: `backend/zhiju/services/settings.py`
- Modify: `backend/zhiju/api/history.py`
- Modify: `backend/zhiju/api/settings.py`
- Modify: `backend/zhiju/models/audit.py`
- Create: `backend/tests/test_history_settings_tenant_isolation.py`

- [ ] **Step 1: 写失败测试**

历史记录、素材处理历史、频道剧种设置、业务审计只返回当前租户。平台 Skill、runtime package、app icon、运行环境与设备总表仍是平台资源，普通租户不能写。

- [ ] **Step 2: 按路由而不是按模块切分 dependency**

租户设置使用 `get_tenant_db`；平台设置使用 `get_current_principal + require_platform_permission + get_db`。`audit_events` 的业务事件 tenant 非空，真正平台事件允许空。

- [ ] **Step 3: 验证并提交**

运行：`uv run pytest backend/tests/test_history_settings_tenant_isolation.py backend/tests/test_history_contract.py backend/tests/test_settings_contract.py backend/tests/test_skill_contract.py -q`

```bash
git add backend/zhiju/services/history.py backend/zhiju/services/settings.py backend/zhiju/api/history.py backend/zhiju/api/settings.py backend/zhiju/models/audit.py backend/tests
git commit -m "feat: isolate tenant history and settings"
```

## Task 11: 修正账号层级和客户设备展示

**Files:**
- Modify: `backend/zhiju/schemas/platform_admin.py`
- Modify: `backend/zhiju/services/platform_admin.py`
- Modify: `backend/zhiju/api/platform_admin.py`
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Modify: `backend/tests/test_platform_admin_api.py`
- Modify: `backend/tests/test_auth_frontend_contract.py`

- [ ] **Step 1: 写当前投诉的回归测试**

账号中心层级固定为“公司 -> 成员”，设备绑定行展示设备名称、设备 ID、绑定用户名/登录名、公司、登录方式、有效期；不再用 UUID 代替可读名称。设置页客户设备清单与账号中心引用同一个设备 ID 和状态来源。

- [ ] **Step 2: 扩展只读 View，不复制设备数据**

```python
class DeviceBindingView(BaseModel):
    id: str
    device_id: str
    device_name: str
    tenant_id: str
    tenant_name: str
    user_id: str
    user_display_name: str
    login_name: str
    status: str
    login_mode: str
    expires_at: datetime | None
```

API 使用 join 生成 View。禁止用 MAC 地址作为身份；可显示的网络/MAC 信息仅作运维备注且不是绑定键。

- [ ] **Step 3: 简化前端层级**

超级管理员先选择公司，再显示该公司的成员与设备绑定；平台设备总表留在设置页。明确标注“客户访问设备”，避免与未来“AI Worker”混淆。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_platform_admin_api.py backend/tests/test_auth_frontend_contract.py -q`

```bash
git add backend/zhiju/schemas/platform_admin.py backend/zhiju/services/platform_admin.py backend/zhiju/api/platform_admin.py assets/app.js assets/styles.css backend/tests
git commit -m "fix: clarify account and access device hierarchy"
```

## Task 12: SSE 按租户分区并封闭内部发布

**Files:**
- Modify: `backend/zhiju/realtime.py`
- Modify: `backend/zhiju/api/realtime.py`
- Modify: `backend/zhiju/app.py`
- Modify: `backend/tests/test_realtime_contract.py`
- Create: `backend/tests/test_realtime_tenant_isolation.py`

- [ ] **Step 1: 写失败测试**

A/B 同时订阅；A 的成功写事件只到 A，平台事件不能误发给所有租户。匿名 stream 返回 401。普通浏览器调用 publish 返回 403/404。

- [ ] **Step 2: 事件显式携带 tenant_id**

把发布接口改为 `publish_change_event(*, tenant_id: str, event: ChangeEvent)`，订阅接口改为 `subscribe(*, tenant_id: str)`；broker 以 tenant ID 分区队列。

中间件从已解析 `request.state.principal` 取 tenant，而不是 body/header。数据库仍是权威；SSE 不保存业务结果。

- [ ] **Step 3: 内部发布接口认证**

删除公开匿名 publish。若旧内部执行仍需要 HTTP publish，则使用现有受控服务身份依赖，并校验事件 tenant 与任务/对象归属；否则改为进程内调用。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_realtime_contract.py backend/tests/test_realtime_tenant_isolation.py -q`

```bash
git add backend/zhiju/realtime.py backend/zhiju/api/realtime.py backend/zhiju/app.py backend/tests
git commit -m "feat: partition realtime events by tenant"
```

## Task 13: 租户唯一键与复合外键

**Files:**
- Create: `backend/alembic/versions/c8e1f4a9b387_add_tenant_unique_keys.py` (`down_revision = "b7d0e3f8a276"`)
- Create: `backend/alembic/versions/d9f2a5b0c498_add_tenant_composite_foreign_keys.py` (`down_revision = "c8e1f4a9b387"`)
- Modify: `backend/zhiju/models/identity.py`
- Modify: `backend/zhiju/models/channel_intelligence.py`
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/models/production.py`
- Modify: `backend/zhiju/models/integration.py`
- Modify: `backend/zhiju/models/youtube.py`
- Modify: `backend/zhiju/models/settings.py`
- Modify: `backend/zhiju/models/demo.py`
- Modify: `backend/zhiju/models/audit.py`
- Create: `backend/tests/test_tenant_relational_constraints.py`

- [ ] **Step 1: 写 MySQL 约束契约测试**

断言每个 tenant-owned 父表存在 `UNIQUE (tenant_id, id)`，子表多父关系存在 `(tenant_id, parent_id) -> parent(tenant_id, id)`；全局目录外键仍保持单列。

- [ ] **Step 2: 先改租户内唯一键**

包括 drama code/title/alias、batch number、integration account key、workspace key、channel drama type、request/idempotency key 和 media storage key。迁移前查询重复；有冲突就停止，不自动改业务键。

- [ ] **Step 3: 按图增加复合外键**

顺序：channel -> drama/schedule -> production/package -> media/image -> OAuth/YouTube/integration。每批先加目标索引再加 FK；downgrade 只移除新 FK/专用索引，不移除 tenant 数据。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_tenant_relational_constraints.py backend/tests/test_model_contract.py -q`

```bash
git add backend/alembic/versions backend/zhiju/models backend/tests
git commit -m "feat: enforce relational tenant boundaries"
```

## Task 14: tenant_id 收口为非空

**Files:**
- Create: `backend/alembic/versions/e0a3b6c1d509_enforce_tenant_not_null.py` (`down_revision = "d9f2a5b0c498"`)
- Modify: `backend/zhiju/models/identity.py`
- Modify: `backend/zhiju/models/channel_intelligence.py`
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/models/production.py`
- Modify: `backend/zhiju/models/integration.py`
- Modify: `backend/zhiju/models/youtube.py`
- Modify: `backend/zhiju/models/settings.py`
- Modify: `backend/zhiju/models/demo.py`
- Modify: `backend/zhiju/models/audit.py`
- Create: `backend/tests/test_tenant_not_null_contract.py`

- [ ] **Step 1: 写完整表清单测试**

平台共享表不得误加 tenant；所有业务表 tenant_id 必须 `nullable=False`。`audit_events` 仅平台事件例外，需由 event type 约束解释。

- [ ] **Step 2: 迁移前再次执行父链审计**

逐图要求 `null_count == 0`、`mismatch_count == 0`、`orphan_count == 0`。任一失败则停止 ALTER。

- [ ] **Step 3: 分图 ALTER NOT NULL 并同步模型**

不要在同一 revision 中重建全部表；按 MySQL 实际 DDL 成本分批执行并记录每张表结果。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_tenant_not_null_contract.py backend/tests/test_model_contract.py -q`

```bash
git add backend/alembic/versions backend/zhiju/models backend/tests
git commit -m "feat: require tenant ownership on business data"
```

## Task 15: 全站认证与权限最后切换

**Files:**
- Modify: `backend/zhiju/app.py`
- Modify: `backend/zhiju/tenant_scope.py`
- Modify: `backend/zhiju/api/channel.py`
- Modify: `backend/zhiju/api/demo.py`
- Modify: `backend/zhiju/api/drama_library.py`
- Modify: `backend/zhiju/api/drama_progress.py`
- Modify: `backend/zhiju/api/feishu_sync.py`
- Modify: `backend/zhiju/api/history.py`
- Modify: `backend/zhiju/api/identity.py`
- Modify: `backend/zhiju/api/image_processing.py`
- Modify: `backend/zhiju/api/integration.py`
- Modify: `backend/zhiju/api/operations.py`
- Modify: `backend/zhiju/api/production.py`
- Modify: `backend/zhiju/api/realtime.py`
- Modify: `backend/zhiju/api/settings.py`
- Modify: `backend/zhiju/api/skill.py`
- Modify: `backend/zhiju/api/youtube.py`
- Modify: `backend/zhiju/api/youtube_oauth.py`
- Create: `backend/tests/test_api_auth_enforcement.py`
- Modify: `backend/tests/test_auth_api.py`

- [ ] **Step 1: 写 223 路由匿名访问矩阵**

公开只允许 health、login、静态页面以及带有效一次性 state 的 OAuth callback。TENANT 路由匿名返回 401、无当前租户返回 403、权限不足返回 403；跨租户对象返回 404。PLATFORM/INTERNAL 使用各自依赖。

- [ ] **Step 2: 给路由应用明确 dependency**

业务路由 `get_tenant_db`；平台路由 `get_current_principal + require_permission`；内部路由服务身份。禁止加入“无会话默认旧租户”的兼容层。

- [ ] **Step 3: 保持登录退出语义**

账号密码登录、退出登录、会话撤销、主账号切换继续通过现有 auth session；客户设备免登录仅允许有效 device-user binding 换取服务器会话，不能绕过租约/停用状态。

- [ ] **Step 4: 验证并提交**

运行：`uv run pytest backend/tests/test_api_auth_enforcement.py backend/tests/test_auth_api.py backend/tests/test_tenant_route_inventory.py -q`

```bash
git add backend/zhiju/app.py backend/zhiju/tenant_scope.py backend/zhiju/api backend/tests
git commit -m "feat: enforce authentication across business APIs"
```

## Task 16: `zhiju_dev` MySQL 迁移演练

**Files:**
- Create: `backend/scripts/verify_tenant_migration.py`
- Create: `docs/testing/central-saas-phase1-dev-migration.md`

- [ ] **Step 1: 写验证器单元测试**

验证器只读检查：Alembic 单一 head、所有业务表 tenant 非空、父子 mismatch=0、两个租户同键共存、跨租户测试实体可回收。失败直接非零退出。

- [ ] **Step 2: 明确连接目标并备份开发库**

先解析 `.env`，程序断言数据库名恰为 `zhiju_dev`。备份文件放 `.runtime/backups/`。若不是 `zhiju_dev`，本任务立即停止。

- [ ] **Step 3: 在开发库执行 migration upgrade**

```bash
ZHJ_ENV=development uv run alembic -c alembic.ini current
ZHJ_ENV=development uv run alembic -c alembic.ini upgrade head
uv run python backend/scripts/verify_tenant_migration.py --expect-database zhiju_dev
```

预期：单一 head、所有 mismatch/null/orphan 为 0。

- [ ] **Step 4: 创建两个临时租户做反向写入验证后清理**

只在 `zhiju_dev` 建 A/B 测试公司和同名业务对象；分别登录读取，并尝试 B ID 注入 A 请求。期望 A/B 数据互不可见、跨租户写为 404、复合 FK 拒绝跨租户父子关系。清理只删除带本次固定 test-run ID 的行。

- [ ] **Step 5: 提交验证器与文档**

```bash
git add backend/scripts/verify_tenant_migration.py docs/testing/central-saas-phase1-dev-migration.md
git commit -m "test: verify mysql tenant migration"
```

## Task 17: 前端双租户行为验收

**Files:**
- Modify: `backend/tests/test_auth_frontend_contract.py`
- Create: `backend/tests/test_tenant_frontend_navigation.py`
- Create: `docs/testing/central-saas-phase1-manual-acceptance.md`

- [ ] **Step 1: 自动化前端契约**

验证登录、退出、超级管理员切换公司、公司成员只见本公司、账号/设备层级、切租户后缓存列表清空并重新请求。前端请求不得提交 tenant_id 来决定作用域。

- [ ] **Step 2: 浏览器手工验收清单**

在独立开发端口启动，使用 A owner、A operator、B owner、super admin 四类账号。逐页检查频道、剧库、排期、工单、运营包、素材、YouTube、历史和设置。每次切公司后网络请求返回正确租户快照。

- [ ] **Step 3: 验证并提交**

运行：`uv run pytest backend/tests/test_auth_frontend_contract.py backend/tests/test_tenant_frontend_navigation.py -q`

```bash
git add backend/tests/test_auth_frontend_contract.py backend/tests/test_tenant_frontend_navigation.py docs/testing/central-saas-phase1-manual-acceptance.md
git commit -m "test: cover tenant switching in web client"
```

## Task 18: 全量回归、审阅与交付边界

**Files:**
- Create: `docs/testing/central-saas-phase1-acceptance-report.md`

- [ ] **Step 1: 跑全量测试**

运行：`uv run pytest -q`

预期：全部 PASS。任何旧测试因认证失败，必须显式登录或使用正确 platform/tenant fixture；不得把认证依赖移除来让测试变绿。

- [ ] **Step 2: 重跑有业务意义的 MySQL 验证器**

运行：`uv run python backend/scripts/verify_tenant_migration.py --expect-database zhiju_dev`

它检测迁移后真实 MySQL 的 null/orphan/mismatch/唯一键与两个租户隔离；失败则修复对应迁移或服务，不继续部署讨论。

- [ ] **Step 3: 审阅分支差异**

审阅 `git diff f452bb8d3400b84d52f6e2f04830ee87aaab4df4...HEAD`，重点检查：裸 `get_db` 业务路由、裸 `session.get`、无 tenant 条件 bulk update/delete、OAuth state、SSE、文件元数据路径、平台表误隔离。

- [ ] **Step 4: 生成验收报告**

报告分开写明：代码完成、自动化测试、`zhiju_dev` 迁移、浏览器验收、生产迁移、合并、部署。后 3 项没有真实执行不得写“已完成”。

- [ ] **Step 5: 提交报告**

```bash
git add docs/testing/central-saas-phase1-acceptance-report.md
git commit -m "docs: report phase one tenant isolation acceptance"
```

## Completion Gate

Phase 1 只有同时满足以下条件才算代码完成：

1. 路由分类覆盖所有 `/api/v3` 路由且互斥。
2. 所有业务表有非空 `tenant_id`，平台共享表未被错误租户化。
3. 两租户的列表、主键、批量写、父子关联、外部同步、SSE 和文件元数据均有反向隔离测试。
4. `zhiju_dev` Alembic 单一 head，null/orphan/mismatch 均为 0。
5. 全量 pytest 通过，浏览器四类账号验收通过。
6. 账号中心清晰展示“公司 -> 成员 -> 客户访问设备”，不使用 MAC 地址作为身份，也不把客户设备称为 Worker。

即使以上全部满足，仍不代表已合并、已生产迁移或已部署。生产动作必须另行获得用户对准确分支、迁移和部署目标的明确授权，并在执行前重新读取生产状态。

## Follow-on Plans

Phase 1 完成后按顺序另写并确认：

1. Phase 2：中心任务表、幂等 POST、状态机、租约、重试、SSE job 通知与公平调度。
2. Phase 3：S3 兼容对象存储、分租户 object key、直传/下载授权、30/7/90 天保留策略和清理任务。
3. Phase 4：Mac Worker Registry、机器密钥、能力/版本/并发、主动领取、固定 handler 与结果提交。
4. Phase 5：Entitlement、套餐并发、用量预留/结算、审计；支付渠道另行决策。
