# Task 13 实施报告

## 结果

- 基线：`13d6d6e24a8e966abf13e3521106905bad9d93c0`
- 分支：`feature/tenant-auth-system`
- 新增 revision：`c8e1f4a9b387 -> d9f2a5b0c498`
- `zhiju_dev` 当前 revision：`d9f2a5b0c498`
- `zhiju_prod`：未连接、未查询、未写入、未迁移
- 19742 开发服务：迁移前由主控确认停止，执行前本机复核无 listener；本任务未重启服务

## 约束合同

- 24 张被业务外键引用的租户父表新增 `UNIQUE (tenant_id, id)`。
- 121 条业务父链替换为 `(tenant_id, parent_id) -> parent(tenant_id, id)`，并逐条建立专用复合索引。
- `languages` / `integrations` / `app_users` / `auth_sessions` / `devices` 五类全局目录或身份引用保持单列外键。
- 租户内业务唯一键覆盖 drama code/title/alias、batch number、integration account key、workspace tenant key、channel drama type code/name、schedule/task/node/audit 幂等键、API request key 和 media storage key。
- `c8e1` 在首个 DDL 前直接查询全部上述重复键；冲突时报错停止，不改写业务键。
- 原 `ON DELETE SET NULL` 的业务外键升级为复合外键时使用 `RESTRICT`，避免 MySQL 将复合外键中的 `tenant_id` 一并置空，也为 Task 14 `tenant_id NOT NULL` 保留可行性；downgrade 恢复原单列外键的 `SET NULL`。
- downgrade 只替换 Task 13 外键、移除 Task 13 专用索引/唯一约束，不删除 `tenant_id` 或租户数据。

## 迁移记录

- 迁移前 `SELECT DATABASE()` 为 `zhiju_dev`，原 revision 为 `b7d0e3f8a276`。
- 备份：`.runtime/backups/task13-before-c8e1-20260913-022137.sql`，19,365,508 bytes，`--skip-events --skip-routines`，输出非空且 dump header 有效。
- `c8e1` 首次成功；information_schema 回读 33/33 个新唯一约束。
- `d9f2` 首次在替换 `channel_initialization_drafts.applied_dna_version_id` 时遇到 MySQL 1091：旧 FK 实际名为 `fk_channel_init_draft_dna`，而非 SQLAlchemy 离线推导名。按要求立即停止。
- 主控授权只读核对后，确认非事务 DDL 已完成 8/121，剩余 113；失败边仅多了目标索引，旧 FK 仍完整，0 broken state。共 15 个待替换旧 FK 名与离线推导不同。
- 迁移修正为在任何新 DDL 前从 information_schema 读取真实 FK/索引定义，验证全部 121 条边处于“旧单列”或“已完成复合”之一；已完成边跳过，已创建的专用索引复用，用实际旧约束名续跑。
- 主控第二次确认后前向续跑成功。逐表 information_schema 回读：62 张子表、121/121 复合 FK、121/121 专用索引全部匹配；5 类全局/身份外键仍为单列。

## 验证

- RED：首次约束契约 `12 failed, 9 passed`，失败原因为父表候选键、复合 FK、租户业务唯一键和 revision 尚未存在。
- 恢复 RED：新增实际 MySQL 旧名/部分 DDL 续跑用例时 `2 failed`，缺少 `_plan_edge` / `_replacement_plan`。
- Focused：`uv run pytest backend/tests/test_tenant_relational_constraints.py backend/tests/test_model_contract.py -q` -> `42 passed`。
- Full backend：`uv run pytest backend/tests -q` -> `1127 passed, 1 warning`。警告为现有 Starlette/httpx 弃用提示。
- 结构：`uv run alembic -c alembic.ini heads` -> `d9f2a5b0c498 (head)`；`uv run python -m compileall -q backend` 通过；`git diff --check` 通过。

## 边界

- 未 push、未 merge、未 deploy、未做业务验收。
- 仅代码、自动测试和 `zhiju_dev` 迁移完成；19742 仍为停止状态。
