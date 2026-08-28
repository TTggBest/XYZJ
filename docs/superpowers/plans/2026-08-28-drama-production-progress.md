# 智矩剧库第二阶段 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每部剧建立唯一制剧进度，按飞书双表头语言页同步 21 种语言覆盖，并在剧库页面提供可维护的进度与语言视图。

**Architecture:** 新增 `DramaProductionState` 保存固定六节点当前状态，复用 `AuditEvent` 记录人工修改；扩展 `Language` 和 `DramaTranslation` 保存优先级及覆盖来源。服务层分别负责进度计算/更新和飞书双表头同步，前端消费聚合 API，不直接解释业务状态。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MySQL、Pydantic、原生 JavaScript/CSS、pytest。

**Spec:** `docs/superpowers/specs/2026-08-28-drama-production-progress-design.md`

## Global Constraints

- 制剧进度只按剧目记录，不包含 `language_id`。
- 六节点固定为网盘下载、统一参数、字幕提取、鬼手上传、角色提取、制作完成。
- 只使用开发 MySQL `zhiju_dev`，不使用 SQLite，不写生产数据库。
- 功能开发保留在 `feature/drama-production-progress`，未经用户单次明确允许不得合并 `dev`。
- 飞书语言页使用前两行解析优先级和语言，不复用普通单表头读取器。
- 智核尚未确认接口时不发起真实智核调用。

---

### Task 1: 制剧进度与语言来源模型

**Files:**
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/models/__init__.py`
- Create: `backend/alembic/versions/<revision>_add_drama_production_progress.py`
- Create: `backend/tests/test_drama_production_progress_contract.py`

**Interfaces:**
- Produces: `DramaProductionState`，每个 `drama_id` 唯一。
- Produces: `Language.priority_tier`。
- Produces: `DramaTranslation.source_type`、`source_synced_at`。
- Produces: `FeishuSyncRun.sync_type == 'drama_languages'` 可通过数据库约束。

- [ ] **Step 1: 写失败的模型与迁移契约测试**，断言六节点字段、四种状态约束、剧目唯一约束、语言优先级和翻译来源字段存在。
- [ ] **Step 2: 运行 `uv run pytest backend/tests/test_drama_production_progress_contract.py -q`**，确认因模型不存在而失败。
- [ ] **Step 3: 实现模型并创建以当前 Alembic head 为父版本的迁移**；已有语言和翻译分别回填 `priority_tier=NULL`、`source_type='manual'`。
- [ ] **Step 4: 运行目标测试和 `uv run alembic upgrade head`**，只迁移 `zhiju_dev`。
- [ ] **Step 5: 提交 `feat: add drama production progress model`**。

### Task 2: 制剧进度服务与 API

**Files:**
- Create: `backend/zhiju/schemas/drama_progress.py`
- Create: `backend/zhiju/services/drama_progress.py`
- Create: `backend/zhiju/api/drama_progress.py`
- Modify: `backend/zhiju/app.py`
- Modify: `backend/zhiju/schemas/drama_library.py`
- Modify: `backend/zhiju/services/drama_library.py`
- Test: `backend/tests/test_drama_production_progress_contract.py`

**Interfaces:**
- Produces: `calculate_progress(state) -> tuple[int, str, str | None]`，返回完成百分比、整体状态和当前节点。
- Produces: `update_drama_progress(session, drama_id, payload) -> DramaProductionStateRead`。
- Produces: `GET /api/v3/drama-production`、`GET/PUT /api/v3/dramas/{drama_id}/production-state`。
- Extends: `DramaLibraryDetail.production_state`。

- [ ] **Step 1: 写失败测试**，覆盖空状态、部分完成、失败状态、顺序不合法、制作完成前置校验和分页筛选。
- [ ] **Step 2: 运行目标测试**，确认服务和路由不存在而失败。
- [ ] **Step 3: 实现 Pydantic 模型和纯计算函数**；节点顺序固定，完成后置节点时前置节点必须完成。
- [ ] **Step 4: 实现读取、人工更新和审计事件，注册 API 并扩展剧库详情**。
- [ ] **Step 5: 运行目标测试及剧库一期契约测试**。
- [ ] **Step 6: 提交 `feat: add drama production progress api`**。

### Task 3: 飞书语言双表头同步

**Files:**
- Modify: `backend/zhiju/services/feishu_sync.py`
- Modify: `backend/zhiju/api/feishu_sync.py`
- Modify: `backend/zhiju/schemas/feishu_sync.py`
- Test: `backend/tests/test_drama_language_sync_contract.py`

**Interfaces:**
- Produces: `FeishuClient.matrix_by_title(wiki_token, title, last_column) -> tuple[str, list[list[str]]]`。
- Produces: `parse_language_matrix(matrix) -> LanguageMatrixPayload`，固定返回 21 种语言定义和剧目覆盖。
- Produces: `sync_drama_languages(session) -> FeishuSyncResult`。
- Produces: `POST /api/v3/feishu-sync/drama-languages`。

- [ ] **Step 1: 写失败测试**，使用真实形状的两行表头覆盖 21 种语言映射、S/A/B/C 优先级、`1`/空白、重复剧名、未知语言和缺失主剧目。
- [ ] **Step 2: 运行目标测试**，确认矩阵读取与同步入口不存在而失败。
- [ ] **Step 3: 实现原始矩阵读取和纯解析函数**，不改变既有单表头同步行为。
- [ ] **Step 4: 实现事务同步**：upsert 语言定义；新增/保留/删除飞书来源覆盖；不删除人工覆盖；记录 `FeishuSyncRun`。
- [ ] **Step 5: 注册接口并运行语言同步、飞书和剧库契约测试**。
- [ ] **Step 6: 提交 `feat: sync drama language coverage`**。

### Task 4: 制剧进度表与剧目详情交互

**Files:**
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Test: `backend/tests/test_drama_production_progress_contract.py`

**Interfaces:**
- Consumes: Task 2/3 的进度分页、详情、更新和语言同步接口。
- Produces: 制剧进度总表、进度编辑表单、剧目详情“制剧进度”标签、S/A/B/C 语言分组和人工覆盖操作。

- [ ] **Step 1: 写失败的前端契约测试**，断言进度入口、六节点列、进度筛选、详情标签、语言分组、语言同步和编辑 action 存在。
- [ ] **Step 2: 运行目标测试**，确认旧页面不满足契约。
- [ ] **Step 3: 扩展前端 state 与路由，新增每部剧一行的制剧进度表和筛选工具栏**。
- [ ] **Step 4: 实现进度详情/编辑；保存后保持滚动位置，不使用整页跳顶刷新**。
- [ ] **Step 5: 扩展语言标签为 S/A/B/C 分组，增加飞书语言同步和人工覆盖操作**。
- [ ] **Step 6: 增加紧凑表格与状态样式，运行 `node --check assets/app.js` 和目标测试**。
- [ ] **Step 7: 提交 `feat: build drama progress workspace`**。

### Task 5: 智核接口需求与开发库验收

**Files:**
- Create: `docs/integrations/zhihe-drama-progress-api-requirements.md`
- Modify only if a verified defect is found in Tasks 1-4.

**Interfaces:**
- Produces: 智核需要提供的字段、变化游标接口、单剧详情接口和事件通知契约。
- Produces: 开发库真实语言覆盖同步结果与完整回归证据。

- [ ] **Step 1: 写智核接口需求文档**，明确稳定剧目 ID、六节点状态/时间/失败原因、剧集数、时长、资源地址、分页游标和事件幂等键。
- [ ] **Step 2: 运行完整后端测试、`node --check assets/app.js` 和 `git diff --check`**。
- [ ] **Step 3: 只读确认当前为 `development / zhiju_dev`，然后执行 Alembic 迁移和一次飞书语言同步**。
- [ ] **Step 4: 第二次同步验证幂等，读回 21 种语言、覆盖数量、剧目总数及人工覆盖保护结果**。
- [ ] **Step 5: 在独立端口验证进度列表、单剧详情、人工更新回滚样例和语言同步 HTTP 接口，停止测试服务**。
- [ ] **Step 6: 提交 `docs: define zhihe drama progress api`，报告代码、测试、迁移和开发数据状态；不合并 `dev`**。
