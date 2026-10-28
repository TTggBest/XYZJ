# 智核制剧进度 API 对接说明

日期：2026-08-31

## 边界

智矩只通过智核提供的 HTTP GET 接口读取制剧进度，不连接智核数据库，不判断智核内部状态是否正确，不改写智核业务。

八节点制剧进度按“每部剧唯一一套”保存；频道可用库存另按正式逐语言最终合成清单匹配。智矩自己维护“网盘下载”和“不制作”，智核同步不覆盖这两项。

## 配置

```env
ZHJ_ZHIHE_API_BASE_URL=http://<zhihe-host>:<port>
ZHJ_ZHIHE_API_TOKEN=<service-token>
```

开发和生产分别配置地址与令牌，不写入业务表。

## 智核已提供的接口

### 增量列表

```http
GET /api/v1/dramas/production-progress
Authorization: Bearer <token>
```

参数：

- `limit`：1 到 500。
- `updated_after`：首页可选，带时区的 ISO 8601 时间。
- `cursor`：上一页返回的游标；使用游标时不再传 `updated_after`。

返回 `items`、`next_cursor`、`has_more` 和 `watermark`。

### 单剧查询

```http
GET /api/v1/dramas/{drama_id}/production-progress
Authorization: Bearer <token>
```

## 智矩采用的字段

剧目顶层字段：

- `drama_id`：智核稳定剧目 ID。
- `chinese_title`：首次建立映射时做精确剧名匹配。
- `episode_count`：剧集数。
- `total_duration_seconds`：合集总时长，单位秒。
- `updated_at`：智核本条进度的更新时间。
- `nodes`：八个节点。
- `finished_languages`：智核正式 `final_compose + language + done` 的语言代码数组。只表示已完成最终成片的语言，不由翻译状态或整剧总进度推断。

八个节点原样采用：

1. `parameter_normalization`
2. `youtube_upload`
3. `copyright_verification`
4. `subtitle_extraction`
5. `guishou_upload`
6. `role_extraction`
7. `tts`
8. `production_completion`

智矩使用智核返回的 `not_started` / `in_progress` / `completed` / `failed`，不在对接层重新判定。节点失败原因汇总到智矩当前的“失败原因”字段。

## 映射和写入规则

1. 先按已保存的智核 `drama_id` 匹配。
2. 首次对接时仅按规范化后的中文剧名精确匹配。
3. 无匹配或多条同名时跳过，不模糊匹配，不自动新建剧目。
4. 智核 `updated_at` 早于已采用版本时跳过，防止旧数据回退；版本相等时，仅允许补入尚未同步的逐语言成片清单，保留既有进度。
5. 同步只覆盖智核负责的八个节点、剧集数、总时长及逐语言成片清单。
6. 清单持久化到 `drama_production_states.finished_languages`：SQL NULL 表示未同步/旧接口未提供，`[]` 表示已同步且没有完成语言。旧接口缺字段时保留原清单，不伪造空库存；后续较新版本的空数组会撤回已失效库存。

## 智矩入口

```http
POST /api/v3/integrations/zhihe/drama-progress/sync
```

制剧进度页“同步智核”按钮调用该接口。当前是人工触发同步；智核尚未提供 Webhook，智矩不伪造实时同步。

频道剧目台账增加“同步成片库存”和“查看未上传”。前者复用同一接口做全量读取（不传 `updated_after`），只同步数据，不启动制作/上传/发布。后者筛出真正未上传的库存；存在上传历史但尚未关联的排期显示“排期待关联”，不冒充未上传。

## 本次修复的发布顺序

1. 智核正式集成并发布新增 `finished_languages` 的只读 API。
2. 智矩备份后执行 Alembic `d83f1e604af2`（基于 `c72a10b01500`），再启动本次代码。只新增可空 JSON 列，不重写原业务数据。
3. 台账执行一次“同步成片库存”，再同步频道视频；核对对应语言可用未上传清单及实际 videoId。代码测试不代替此项线上业务验收。
