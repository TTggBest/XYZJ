# Task 10 Fix 1 实施报告

## 范围

- 基线：`1967ffabe938dd13c7f13b9c80107d4d8b3dfd6f`
- 修复 Task 10 独立审查的唯一 Important：实体时间线对他租户实体 ID 返回了 `200 []`，而非 `404`。
- 仅修改历史服务、Task 10 租户隔离测试和本报告。

## 根因与修复

- 根因：`get_entity_timeline()` 只查询已被 `TenantSession` 过滤的事件行，没有先验证 URL 中的实体 ID 是否属于当前租户。因此他租户 ID、不存在 ID 和“本租户存在但无事件”被同样处理为空列表。
- 修复：建立 29 个当前业务历史 `entity_type` 到租户实体模型的显式映射；进入事件查询前先调用 `require_tenant_entity()`。未支持类型、他租户 ID 和不存在 ID 统一返回 `404`；当前租户真实存在但无事件的实体保持 `200 []`。
- 存在性不依赖事件是否为空，因此不会通过时间线响应区分他租户实体与不存在实体。

## TDD 与验证证据

- RED：定向回归首次结果为 `3 failed, 1 passed`。他租户 `operation_task/task-b` 和不存在 `operation_task/task-missing` 均实际返回 `200`，全部业务历史实体类型映射不存在；本租户无事件实体正确返回 `200 []`。
- GREEN：同一定向回归为 `4 passed`。
- Task 10 focused：`uv run pytest backend/tests/test_history_settings_tenant_isolation.py backend/tests/test_history_contract.py backend/tests/test_settings_contract.py backend/tests/test_skill_contract.py -q` 结果 `31 passed`。
- Full backend：`uv run pytest backend/tests -q` 结果 `1099 passed`。
- 两组验证均仅使用 SQLite/内存或 pytest 临时测试资源；唯一警告是已知 Starlette/httpx2 弃用警告。

## 交付边界

- 未访问或修改任何实际数据库，未触碰 19742 开发服务。
- 未调用外部服务，未执行 push、merge、deploy 或生产验收。
