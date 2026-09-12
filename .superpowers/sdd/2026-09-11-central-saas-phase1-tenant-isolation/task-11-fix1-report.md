# Task 11 fix 1 report — 对齐客户访问设备状态视图

状态：已完成代码与自动化验证，随提交 `fix: align access device status views` 交付。未访问真实数据库或外部服务，未 push、merge 或 deploy。

## 根因

`DeviceBindingView.status` 来自 `device_user_bindings.status`，而设置页 `/devices` 的同一设备状态来自 `devices.status`。因此支持数据中的“设备 inactive、绑定 active”会在账号中心显示为启用、设置页显示为停用；单一 `status` 无法表达两个独立生命周期。

修复后 View 不保留含混的 `status`，而是明确返回：

- `device_status`：`devices.status`，账号中心的“设备状态”列使用此字段。
- `binding_status`：`device_user_bindings.status`，撤销按钮及绑定授权判断使用此字段。

前端状态标签同步覆盖 `enabled/active/inactive`，并补齐当前绑定与设备状态 `suspended/revoked/retired`。

## RED

先加入“device inactive + binding active”API 与真实前端回归：

```text
uv run pytest backend/tests/test_platform_admin_api.py::test_binding_view_keeps_inactive_device_status_distinct_from_active_binding backend/tests/test_auth_frontend_contract.py::test_real_app_account_center_selects_company_before_showing_members_and_access_devices -q
2 failed
```

失败分别为 API 响应缺少 `device_status`，以及账号中心无法显示 inactive 对应的“停用”。

另加入 revoked 绑定反例，并将操作分支临时恢复为旧的含混 `binding.status` 做 mutation check：

```text
uv run pytest backend/tests/test_auth_frontend_contract.py::test_real_app_account_center_selects_company_before_showing_members_and_access_devices -q
1 failed: 2 !== 1
```

它证明测试能阻止已撤销绑定继续显示“撤销绑定”按钮。

## GREEN

实现显式双状态字段后，首轮回归：

```text
uv run pytest backend/tests/test_platform_admin_api.py::test_binding_view_keeps_inactive_device_status_distinct_from_active_binding backend/tests/test_auth_frontend_contract.py::test_real_app_account_center_selects_company_before_showing_members_and_access_devices -q
2 passed, 1 warning
```

恢复 `binding_status` 操作分支后 mutation 回归：`1 passed`。

Task 11 指定测试：

```text
uv run pytest backend/tests/test_platform_admin_api.py backend/tests/test_auth_frontend_contract.py -q
177 passed, 1 warning
```

相关平台设备与认证上下文契约：

```text
uv run pytest backend/tests/test_runtime_device_contract.py backend/tests/test_auth_context.py -q
61 passed, 1 warning
```

全后端：

```text
uv run pytest backend/tests -q
1061 passed, 1 warning
```

唯一 warning 为现有 Starlette `TestClient` 对 httpx 的弃用提示。

## 改动范围

- `backend/zhiju/schemas/platform_admin.py`
- `backend/zhiju/services/platform_admin.py`
- `assets/app.js`
- `backend/tests/test_platform_admin_api.py`
- `backend/tests/test_auth_frontend_contract.py`
- 本报告

`backend/zhiju/api/platform_admin.py` 已通过 `response_model=DeviceBindingView` 使用更新后的契约，无需增加路由或兼容层。未修改 Task 7/12 文件。
