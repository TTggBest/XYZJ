# 智核制剧进度 API 需求

日期：2026-08-28

## 目标

智矩通过正式 HTTP API 获取智核的制剧进度，不直接读写智核数据库。制剧进度按剧目记录，与目标语言无关。

## 剧目标识

智核必须为每部剧提供不变的 `drama_id`，并返回：

- `drama_id`：智核稳定剧目 ID。
- `chinese_title`：中文主剧名，用于首次建立智核 ID 与智矩 `drama_id` 的映射。
- `updated_at`：该剧在智核的最后变更时间，ISO 8601，包含时区。

建立映射后，后续同步以稳定 `drama_id` 为准，不依赖剧名重新匹配。

## 进度字段

每部剧返回以下六个固定节点：

1. `cloud_download`：网盘下载。
2. `parameter_normalization`：统一参数。
3. `subtitle_extraction`：字幕提取。
4. `guishou_upload`：鬼手上传。
5. `role_extraction`：角色提取。
6. `production_completion`：制作完成。

每个节点包含：

- `status`：`not_started` / `in_progress` / `completed` / `failed`。
- `started_at`：开始时间，可空。
- `completed_at`：完成时间，可空。
- `failure_reason`：失败原因，可空。
- `resource_uris`：该节点产物定位地址数组，可空。

剧目顶层另需返回：

- `episode_count`：剧集数。
- `total_duration_seconds`：剧集合集总时长，秒。
- `updated_at`：该进度整体最后变更时间。

## 查询接口

### 增量查询

`GET /api/v1/dramas/production-progress`

参数：

- `cursor`：上一页返回的不透明游标，首页留空。
- `limit`：建议默认 100，最大 500。
- `updated_after`：可选 ISO 8601 时间，用于首次补同步。

返回：`items`、`next_cursor`、`has_more`。同一游标重试必须返回同一分页边界。

智矩保存最后成功消费的游标和高水位时间。事件通知丢失、中断恢复或人工补同步时，都从该水位使用 `updated_after` 重新拉取，不要直接修改智核数据库。

### 单剧查询

`GET /api/v1/dramas/{drama_id}/production-progress`

返回该剧完整的六节点、剧集数、总时长和资源地址。剧目不存在返回 404。

## 事件通知

智核可在节点状态变化后向智矩发送：

`POST /api/v3/integrations/zhihe/drama-progress-events`

请求包含：

- `event_id`：智核生成的唯一事件 ID，重试保持不变。
- `event_type`：固定为 `drama.production_progress.changed`。
- `occurred_at`：事件时间。
- `drama_id`：智核稳定剧目 ID。
- `updated_at`：该剧进度版本时间。

事件只用于触发智矩拉取单剧最新状态，不把事件载荷直接当成最终业务数据。

智矩必须按 `event_id` 幂等受理：首次接收记录事件并触发拉取，重复接收返回与首次一致的成功确认，不重复应用状态。如果新拉取数据的 `updated_at` 早于或等于当前已采用版本，智矩跳过回写，防止乱序事件回退进度。

智矩还需提供人工触发的全量/按时间补同步入口；补同步复用上述查询 API 和同一幂等写入逻辑，不新建第二套进度数据通道。

## 认证与错误

- 本地化部署先支持智矩向智核发起的服务凭证；具体认证头由智核确认。
- 400：参数或状态值不合法。
- 401/403：凭证不合法或无权读取。
- 404：剧目不存在。
- 429/5xx：智矩会延时重试，不将本次失败写成制剧节点失败。

## 智核需要回复的事项

1. 稳定 `drama_id` 的现有字段和生成规则。
2. 六个节点在智核现有状态中的精确映射。
3. 剧集数、总时长和四类产物地址的现有字段。
4. 可用的认证方式、服务地址和网络边界。
5. 是否能提供增量游标和状态变化通知。
