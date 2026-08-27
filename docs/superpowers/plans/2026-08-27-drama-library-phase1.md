# 智矩剧库第一阶段 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将剧库升级为支持飞书增量同步、分页检索、完整编辑、批量录入、语言覆盖和频道发布分布的 MySQL 主数据页面。

**Architecture:** 保留既有 `/api/v3/dramas` 供排期选择器使用，新建聚合型 `drama_library` 服务与 API 承担分页、详情、编辑和批量录入；飞书同步复用现有客户端和 `FeishuSyncRun`，但按 Sheet 标题动态解析剧库表。前端仍使用现有单页原生 JavaScript，仅替换剧库视图和相关交互。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MySQL、Pydantic、原生 JavaScript/CSS、pytest。

**Spec:** `docs/superpowers/specs/2026-08-27-drama-library-phase1-design.md`

## Global Constraints

- 只使用开发 MySQL，不创建或使用 SQLite，不写生产数据库。
- 功能开发留在 `feature/drama-library-phase1`，未经用户单次明确允许不得合并 `dev`。
- 剧目生产进度不按语言拆分，本阶段不创建制剧进度表。
- 飞书状态“制作”或空白映射 `active`，“已删”映射 `archived`，不物理删除。
- 到期日期按北京时间自然日落为当天 `23:59:59`。
- 同步按标题实时解析“剧库表”，不写死 Sheet ID。

---

### Task 1: 剧库来源字段与同步类型迁移

**Files:**
- Create: `backend/alembic/versions/<revision>_add_drama_library_source_fields.py`
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/models/production.py`
- Test: `backend/tests/test_drama_library_contract.py`

**Interfaces:**
- Produces: `Drama.batch_name`, `source_type`, `source_sheet_id`, `source_row_number`, `source_synced_at`。
- Produces: `FeishuSyncRun.sync_type == "dramas"` 可通过数据库约束。

- [ ] **Step 1: 写失败的模型契约测试**，断言五个字段、`source_type` 合法值及迁移的 `down_revision` 指向当前 head。
- [ ] **Step 2: 运行 `uv run pytest backend/tests/test_drama_library_contract.py -q`**，确认字段不存在而失败。
- [ ] **Step 3: 增加模型字段和 Alembic 迁移**；已有剧目回填 `source_type='manual'`，然后设为非空。
- [ ] **Step 4: 运行该测试并执行 `uv run alembic upgrade head`**，确认开发 MySQL 迁移成功。
- [ ] **Step 5: 提交 `feat: add drama library source metadata`**。

### Task 2: 分页、详情、编辑与批量服务

**Files:**
- Create: `backend/zhiju/schemas/drama_library.py`
- Create: `backend/zhiju/services/drama_library.py`
- Create: `backend/zhiju/api/drama_library.py`
- Modify: `backend/zhiju/app.py`
- Test: `backend/tests/test_drama_library_contract.py`

**Interfaces:**
- Produces: `list_drama_library(session, filters) -> DramaLibraryPage`。
- Produces: `get_drama_library_detail(session, drama_id) -> DramaLibraryDetail`。
- Produces: `update_drama_library_item(session, drama_id, payload)` 与 `bulk_upsert_dramas(session, rows)`。
- Produces routes: `GET /api/v3/dramas/library`, `GET/PATCH /api/v3/dramas/{drama_id}`, `POST /api/v3/dramas/bulk`。

- [ ] **Step 1: 写失败的 API 路由和纯函数测试**，覆盖分页参数、状态筛选、冲突检测、空文本归一化和 active 选择规则。
- [ ] **Step 2: 运行目标测试**，确认路由和服务尚不存在。
- [ ] **Step 3: 实现 Pydantic 模型和服务**；分页查询用数据库聚合统计语言数和频道数，详情查询返回语言单元格与 YouTube 视频分布。
- [ ] **Step 4: 实现 PATCH 与批量 upsert**；同一批次先检测规范化剧名重复，逐行结果返回 `inserted/updated/conflict`，不物理删除。
- [ ] **Step 5: 注册 API，运行目标测试和 `backend/tests/test_operations_contract.py`**。
- [ ] **Step 6: 提交 `feat: add drama library management api`**。

### Task 3: 飞书剧库增量同步

**Files:**
- Modify: `backend/zhiju/config.py`
- Modify: `backend/zhiju/services/feishu_sync.py`
- Modify: `backend/zhiju/api/feishu_sync.py`
- Test: `backend/tests/test_feishu_sync_contract.py`
- Test: `backend/tests/test_drama_library_contract.py`

**Interfaces:**
- Produces: `FeishuClient.sheet_id_by_title(wiki_token, "剧库表") -> str`。
- Produces: `sync_dramas(session) -> FeishuSyncResult`。
- Produces route: `POST /api/v3/feishu-sync/dramas`。

- [ ] **Step 1: 写失败测试**，覆盖标题解析、九列映射、状态映射、北京时间到期日、重复标题失败和一致数据跳过。
- [ ] **Step 2: 运行目标测试**，确认新同步入口不存在。
- [ ] **Step 3: 为 Feishu 客户端增加一次认证后解析工作簿及 Sheet 元数据的方法**，返回标题完全等于“剧库表”的 Sheet ID。
- [ ] **Step 4: 实现 `sync_dramas`**；先完整校验所有行，再在一个事务内新增/更新/跳过，失败写回 `FeishuSyncRun`。
- [ ] **Step 5: 注册接口并运行飞书与剧库目标测试**。
- [ ] **Step 6: 提交 `feat: sync drama catalog from feishu`**。

### Task 4: 剧库总表与详情交互

**Files:**
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Test: `backend/tests/test_drama_library_contract.py`

**Interfaces:**
- Consumes: Task 2/3 的分页、详情、PATCH、批量和同步接口。
- Produces: 剧库总表、基本资料/语言覆盖/频道分布详情、单条新增、CSV 批量录入。

- [ ] **Step 1: 写失败的前端契约测试**，断言筛选字段、三个操作按钮、三个详情标签、分页按钮及同步 action 存在。
- [ ] **Step 2: 运行目标测试**，确认旧页面不满足契约。
- [ ] **Step 3: 扩展前端 state**，保存剧库分页、筛选和详情标签；加载剧库时只请求分页 API，不把 327 条全部塞入全局列表。
- [ ] **Step 4: 实现总表**，展示序号、剧名/编号、批次、到期、概述、语言覆盖、频道数、状态和详情；增加同步、新增、批量和分页。
- [ ] **Step 5: 实现详情抽屉和编辑表单**，三个标签分别使用详情 API 数据；保存后刷新当前页并保持滚动位置。
- [ ] **Step 6: 实现 CSV 文件解析上传**，浏览器只负责读取 CSV 文本并提交结构化行，服务端负责业务校验。
- [ ] **Step 7: 增加紧凑表格、状态汇总、详情标签和响应式样式，运行前端契约测试**。
- [ ] **Step 8: 提交 `feat: build drama library workspace`**。

### Task 5: 开发 MySQL 验收与真实飞书同步

**Files:**
- Modify only if a verified defect is found in Tasks 1-4.

**Interfaces:**
- Consumes: 完整一期功能。
- Produces: 开发数据库中的真实剧库同步结果和回归证据。

- [ ] **Step 1: 运行剧库、飞书、运营、模型和健康检查测试**；任何失败先定位并只修复相关问题。
- [ ] **Step 2: 在开发环境调用一次 `/api/v3/feishu-sync/dramas`**，确认读取实时标题为“剧库表”的 Sheet。
- [ ] **Step 3: 用 MySQL 读回总数、`active/archived` 数量、三个抽样剧目的九字段、原有 20 条 YouTube 关联和同步记录**。
- [ ] **Step 4: 使用浏览器检查桌面宽度下的列表、详情、编辑、同步和分页，并确认页面不因更新跳回顶部。**
- [ ] **Step 5: 运行 `git diff --check` 与完整相关测试，提交必要修复 `fix: complete drama library phase one`**。
- [ ] **Step 6: 报告代码、测试、迁移和开发数据状态；保持功能分支，不合并 `dev`。**
