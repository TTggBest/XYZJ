# Feishu Channel Schedule Sync Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将飞书 30 个频道排期表只读、幂等同步到智矩，并提供按频道查看完整历史/未来排期的分页表格。

**Architecture:** 公共剧库保持频道无关；频道关系只落在 `ChannelScheduleEntry`。专用飞书同步服务先解析并校验全部工作表，再在单个事务中按频道、当地发布日期、档位 upsert；系统人工排期仍走原有制剧完成门槛。新增独立分页查询为频道完整排期页面供数。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MySQL `zhiju_dev`、Pydantic、原生 JavaScript/CSS、pytest。

---

### Task 1: 扩展频道排期来源字段

**Files:**
- Modify: `backend/zhiju/models/operations.py`
- Modify: `backend/zhiju/schemas/operations.py`
- Create: `backend/alembic/versions/<revision>_add_feishu_channel_schedule_fields.py`
- Create: `backend/tests/test_feishu_channel_schedule_contract.py`

- [ ] **Step 1: 写失败测试**，断言排期模型、读取 Schema 和 Alembic 迁移包含来源、视频、上传、上线、任务写入字段及合法默认值。
- [ ] **Step 2: 运行 `PYTHONPATH=backend ../../.venv/bin/python -m pytest backend/tests/test_feishu_channel_schedule_contract.py -q`**，确认因字段不存在而失败。
- [ ] **Step 3: 最小实现模型、Schema 与迁移**。迁移只增加所需列和来源索引，不改公共剧库表，不删除既有约束。
- [ ] **Step 4: 只读确认数据库 URL 和 `SELECT DATABASE()` 为 `zhiju_dev` 后运行 Alembic upgrade head**，随后检查版本、列与既有排期数量。
- [ ] **Step 5: 重跑目标测试并提交**：`feat: add Feishu schedule provenance fields`。

### Task 2: 实现飞书排期解析与全量校验

**Files:**
- Modify: `backend/zhiju/config.py`
- Modify: `backend/zhiju/services/feishu_sync.py`
- Modify: `backend/tests/test_feishu_channel_schedule_contract.py`

- [ ] **Step 1: 写解析测试**，覆盖频道目录映射、主辅档、布尔标记、Video ID 链接规范化、北京时间转频道当地时间、标题/别名匹配和异常日期修正计数。
- [ ] **Step 2: 写失败测试**，覆盖未知频道、未知剧目、未知档位、普通非法日期必须中止而不是跳过或新建主档。
- [ ] **Step 3: 运行目标测试确认失败**。
- [ ] **Step 4: 扩展 FeishuClient 的工作表列表/按 sheet id 读取能力，并实现纯解析与解析结果结构**。只使用 GET/认证请求，不新增飞书写方法。
- [ ] **Step 5: 实现频道、剧目/别名和档位严格匹配；仅对已确认的 `2026-08-010 12:00` 做窄范围修正**。
- [ ] **Step 6: 重跑目标测试并提交**：`feat: parse Feishu channel schedules`。

### Task 3: 实现幂等同步 API

**Files:**
- Modify: `backend/zhiju/services/feishu_sync.py`
- Modify: `backend/zhiju/api/feishu_sync.py`
- Modify: `backend/zhiju/schemas/feishu_sync.py`
- Modify: `backend/tests/test_feishu_channel_schedule_contract.py`

- [ ] **Step 1: 写服务测试**，同一份排期第一次插入、第二次不重复；变更视频/状态后更新；发生任一匹配错误时事务回滚。
- [ ] **Step 2: 写 API 合同测试**，断言 `POST /api/v3/feishu-sync/channel-schedules` 存在并返回工作表数、行数、插入、更新、跳过、修正数。
- [ ] **Step 3: 运行目标测试确认失败**。
- [ ] **Step 4: 实现同步 upsert**，复用排期唯一约束，创建/维护主选候选记录，但不创建 OperationTask；状态映射为上线=`published`、已上传=`confirmed`、否则=`planned`。
- [ ] **Step 5: 处理同档位已存在排期的更新历史与审计记录，保证重跑不制造无意义历史**。
- [ ] **Step 6: 重跑目标测试并提交**：`feat: sync Feishu channel schedules`。

### Task 4: 实现频道完整排期分页查询

**Files:**
- Modify: `backend/zhiju/services/operations.py`
- Modify: `backend/zhiju/api/operations.py`
- Modify: `backend/zhiju/schemas/operations.py`
- Create: `backend/tests/test_channel_schedule_full_view.py`

- [ ] **Step 1: 写失败测试**，覆盖必填频道、默认正序、倒序、剧名/编号/Video ID 搜索、50/100/150 页大小及总数。
- [ ] **Step 2: 运行目标测试确认失败**。
- [ ] **Step 3: 新增 `GET /api/v3/schedules/channel-view` 分页查询**，复用现有关联查询但不改变旧 `/overview` 的响应合同。
- [ ] **Step 4: 重跑目标测试并提交**：`feat: add full channel schedule query`。

### Task 5: 实现频道完整排期界面与同步入口

**Files:**
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Modify: `backend/tests/test_channel_schedule_full_view.py`

- [ ] **Step 1: 写前端合同测试**，断言视图切换、同步按钮、频道筛选、搜索、正倒序、分页选择和所需列存在。
- [ ] **Step 2: 运行目标测试确认失败**。
- [ ] **Step 3: 在排期页加入“按日查看 / 频道完整排期”切换；完整视图读取分页 API，默认 50 条正序**。
- [ ] **Step 4: 加入“同步飞书排期”二次确认和结果提示；按钮只调用智矩同步 API，不写飞书**。
- [ ] **Step 5: 调整表格为单一页面纵向滚动、表内仅横向滚动，避免恢复双层纵向滚动问题**。
- [ ] **Step 6: 运行目标测试、`node --check assets/app.js` 并提交**：`feat: add channel schedule full view`。

### Task 6: 开发库真实同步与验收

**Files:**
- Modify: `docs/superpowers/specs/2026-08-29-feishu-channel-schedule-sync-design.md`（仅当实测发现需要记录的已确认约束）

- [ ] **Step 1: 只读核对 `zhiju_dev`、Alembic head、30 个频道、关键排期列与迁移前数量**。
- [ ] **Step 2: 在独立测试端口启动功能分支服务，调用飞书同步一次**，核对 30 个频道表、1591 条源排期与异常日期修正结果；不得回写飞书。
- [ ] **Step 3: 再同步一次**，确认没有重复排期，并核对插入/更新/跳过数量与数据库互斥总数。
- [ ] **Step 4: 通过浏览器真实检查按日视图和频道完整排期**，验证频道切换、搜索、正倒序、50/100/150 分页、视频链接和状态列。
- [ ] **Step 5: 关闭测试服务**。

### Task 7: 完整验证与交付候选

**Files:**
- Review: 本分支全部改动

- [ ] **Step 1: 运行后端全量测试**：`PYTHONPATH=backend ../../.venv/bin/python -m pytest -q`。
- [ ] **Step 2: 运行前端语法检查**：`node --check assets/app.js`。
- [ ] **Step 3: 运行迁移与差异检查**：Alembic current/check、`git diff --check`、`git status --short --branch`。
- [ ] **Step 4: 核对公共剧库没有频道外键、同步没有 Feishu 写请求、系统人工排期门槛未被放宽**。
- [ ] **Step 5: 提交剩余最小修正，整理提交列表与证据；不合并 `dev`，交由“智矩 Dev 合并管理员”在用户再次明确授权后处理**。

