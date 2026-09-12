# 智矩实时状态设计

## 目标

成功业务写入后，已打开的页面可以通过当前 API 进程的 SSE 通知立即重读 MySQL 中的最新数据，不使用定时轮询。

## 数据流

1. 浏览器通过 `EventSource` 订阅当前同源 API 的 `/api/v3/events/stream`，并使用现有登录会话认证。
2. 任何成功的租户业务写请求完成后，处理该请求的 API 进程向当前租户的进程内 broker 发送一条轻量变更通知。
3. 前端不直接使用通知里的业务数据，而是重新请求同源 API，从 MySQL 读取最新状态。
4. SSE 断线由浏览器自动重连；重连成功后完整刷新当前页面，不需要持久化消息队列。

## 运行配置

- `studio`、`worker` 和 `builder` 运行配置都留空 `ZHJ_REALTIME_HUB_URL`。
- `/api/v3/realtime/config` 始终向浏览器返回同源 `/api/v3/events/stream`，不宣告远程 Hub。
- Phase 1 不提供匿名 HTTP publish 接口，也不定义 Worker 跨进程通知协议。

## 边界

- MySQL 是唯一业务事实源，SSE 只传输“数据已变更”。
- 通知不包含完整工单、标题、说明或密钥。
- 通知发送失败、断线或跨进程不可达不回滚已提交的业务数据；用户刷新或页面重连后再从 MySQL 校正。
- 本阶段不引入 Redis、WebSocket 或轮询任务。
