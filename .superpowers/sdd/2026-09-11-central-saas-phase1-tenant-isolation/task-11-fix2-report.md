# Task 11 fix 2 report — 同步独立账号中心设备契约

状态：已完成代码与自动化验证，随提交 `fix: update account center device contract` 交付。未访问真实数据库或外部服务，未 push、merge 或 deploy。

## 根因

fix1 已将 `DeviceBindingView` 收口为 `device_name` / `device_status` / `binding_status` / `login_mode` / `user_display_name` / `login_name` 等明确字段，但 `assets/account-center.js` 的独立渲染路径仍读取已删除的 `status` / `is_default` / `auto_login_enabled`。旧测试 fixture 自己伪造了这三个旧字段，因此掩盖了可读名称丢失、登录方式误报以及 revoked 绑定仍显示撤销按钮的问题。

`index.html` 实际会在 `app.js` 之前加载 `account-center.js`；只具有 `platform.device.manage` 且未选中公司的设备管理员会直接使用该独立渲染路径，因此无需修改模板引用。

## RED

先将旧 fixture 替换为完整的新 `DeviceBindingView` 响应，包含 inactive 设备、revoked 绑定、password 登录方式和设备/用户可读字段，然后运行：

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest backend/tests/test_auth_frontend_contract.py::test_account_center_platform_lists_companies_users_bindings_without_http_enrollment -q
```

结果：`1 failed`。失败输出确认页面没有设备名称，用户仍回退为 UUID，登录方式显示旧文案，revoked 绑定仍产生撤销按钮。

## GREEN

最小更新独立绑定行后，它直接展示设备名称/ID、用户姓名/登录名和公司名称；设备状态只读 `device_status`，操作只读 `binding_status`，登录方式只读 `login_mode`。未恢复旧响应字段，未加兼容层。

单用例回归：`1 passed`。

账号中心 / 真实前端 / platform admin 定向：

```text
5 passed, 1 warning in 0.89s
```

Task 11 完整指定测试：

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest backend/tests/test_platform_admin_api.py backend/tests/test_auth_frontend_contract.py -q
177 passed, 1 warning in 8.44s
```

唯一 warning 为现有 Starlette `TestClient` 对 httpx 的弃用提示。本任务未重复运行全 backend collection，由主控在共享 Task 8 OAuth 工作稳定后统一验证。

## 改动范围

- `assets/account-center.js`
- `backend/tests/test_auth_frontend_contract.py`
- 本报告

未修改、暂存或回滚 Task 8 OAuth 文件；未改动模板、API、schema、service 或数据库对象。
