# Task 10 实施报告

## 范围

- 基线：`f9ebff5a75df01bb47a39a423830101d1642a47a`
- 分支：`feature/tenant-auth-system`
- 任务：历史、审计与租户设置隔离
- Task 9 仅做现状阅读，未修改其同步、demo 或迁移实现。

## 实现结果

- 系统事件、业务审计、实体时间线、任务事件、排期历史和视频状态历史全部改用 `get_tenant_db`；历史服务拒绝裸 `Session`，且主键历史入口先校验父实体归属。
- 素材处理历史保持 Task 7 的 TenantSession 隔离，新的两租户测试将其与其他历史入口一起覆盖。
- 频道短剧类型与频道初始化规则路由使用 TenantSession；短剧类型列表、新建、更新服务拒绝裸 `Session`，他租户 ID 更新返回 404。
- runtime overview/package、app icon、运行环境和客户访问设备继续使用平台 `get_db`；读取要求已登录 principal，写入要求平台管理员。`PUT /devices/register` 的真实写入入口也已同步收口，但仍保持平台 Session。
- Skill/SkillVersion 仍是平台全局目录，未加 `tenant_id`；读取要求登录，新建、修改、发布要求平台管理员。
- `AuditEvent` 在 ORM 写入时拒绝缺少 tenant 的业务实体事件；只有明确的平台实体类型可以保持 `tenant_id = NULL`。TenantSession 中的业务审计继续由会话自动填充当前租户。
- 未新增迁移，未修改数据库 schema，未访问外部服务。首轮 full backend 暴露一个旧设置测试在调用服务前打开活动 engine 连接；新的服务守卫在任何业务 SQL 或写入前拒绝了调用，测试事务随后回滚。该测试及运行环境测试均已改为纯 SQLite 装配，最终验证不再通过这些入口触及活动数据库。

## TDD 证据

- RED 1：新增隔离测试首次运行为 `5 failed, 1 passed`，分别命中历史/设置裸 Session、history/settings/Skill 路由 dependency 和空 tenant 业务审计缺口。
- RED 2：补充真实设备写入入口后，定向测试因 `PUT /devices/register` 缺少平台权限而失败。
- GREEN：`uv run pytest backend/tests/test_history_settings_tenant_isolation.py backend/tests/test_history_contract.py backend/tests/test_settings_contract.py backend/tests/test_skill_contract.py -q` 结果 `27 passed`。
- Full backend：`uv run pytest backend/tests -q` 结果 `1095 passed`。
- 已知非任务警告：FastAPI TestClient 发出 1 条 Starlette/httpx2 弃用警告。

## 交付边界

- 已完成代码、TDD 回归、定向测试和 full backend 测试。
- 未执行业务数据查询或修改，未执行迁移、push、merge 或 deploy；未做生产验收声明。
