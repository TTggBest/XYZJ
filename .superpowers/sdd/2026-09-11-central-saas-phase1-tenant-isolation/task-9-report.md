# Task 9 实施报告

## 范围

- 基线：`af21985c12942e39ed0377a3214dd8b568a25dcf`
- 分支：`feature/tenant-auth-system`
- 任务：集成账号、飞书、智核进度同步与演示数据租户隔离
- Task 8 仅做现状阅读，未修改其 OAuth/YouTube 实现。

## 实现结果

- `integration_credentials` 从 `integration_accounts` 唯一继承租户；`demo_data_entities` 从 `demo_data_batches` 唯一继承租户。
- `feishu_sync_runs` 要求已绑定租户；所有飞书、智核和 demo 真实服务入口拒绝裸 `Session`，仅接受显式 `TenantSession`。
- 集成账号、凭证、生产批次、飞书任务幂等键、demo batch/entity 改为租户内唯一。
- 飞书同名剧目需在 A/B 租户各自建立，因此 `dramas.normalized_title` 一并收口为 `(tenant_id, normalized_title)`。
- A 租户的同步查询、新建和更新由 TenantSession 过滤，不会命中 B 的同名频道、剧目、批次、任务、工单或运营包。
- `GET /integrations` 为已登录用户可读的平台目录；`POST /integrations` 要求平台管理权限；account/credential/sync/demo 路由使用 TenantSession。

## TDD 证据

- RED：新增测试首次运行 `10 failed`，分别命中缺失 revision、子表无 tenant、全局唯一冲突、裸 Session 可入口和路由 dependency 错误。
- GREEN：`uv run pytest backend/tests/test_external_sync_tenant_isolation.py backend/tests/test_feishu_* backend/tests/test_integration_contract.py backend/tests/test_demo_contract.py backend/tests/test_zhihe_progress_sync.py -q` 结果 `58 passed`。
- Full backend：`uv run pytest backend/tests -q` 结果 `1088 passed`。
- 已知非任务警告：FastAPI TestClient 发出 1 条 `httpx2` 弃用警告。

## `zhiju_dev` 迁移证据

- 迁移前：`DATABASE() = zhiju_dev`，Alembic current = `a6c9d2e7f165`。
- 备份：`.runtime/backups/zhiju_dev_before_b7d0e3f8a276_20260913_012823.sql`，19,355,834 bytes，非空，不含 event/routine 定义。
- 执行：只升级精确 revision `b7d0e3f8a276`。
- 回读：`integration_accounts=0`、`integration_credentials=0`、`production_batches=11`、`operation_tasks=414`、`demo_data_batches=1`、`demo_data_entities=163`、`feishu_sync_runs=47`、`dramas=737`。
- 全部相关表 `tenant_id IS NULL = 0`；credential/account 与 demo entity/batch 父链 mismatch = 0；7 个新复合唯一索引的首列均回读为 `tenant_id`。

## 交付边界

- 代码、定向测试、full backend 测试和 `zhiju_dev` 精确迁移已执行。
- 未查询或修改 `zhiju_prod`；未 push、merge 或 deploy；未做生产验收声明。
