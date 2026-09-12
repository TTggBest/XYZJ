# Task 9 Review Fix 1 报告

## 修复范围

- 针对审查 Critical：同一 demo package 在第二个租户导入时撞上全局唯一的模拟远程标识。
- 没有修改 schema 或迁移，没有放松真实 YouTube channel/video 以及 drama code 的全局唯一约束。
- 只修改 demo 直接服务、Task 9 回归测试和本报告；未触碰共享 Task 10 文件。

## 标识分类与最小修法

- 全局唯一：`Channel.youtube_channel_id`、`Drama.drama_code`、`ChannelScheduleEntry.idempotency_key`、`YoutubeVideo.youtube_video_id`。demo 生成值加入 demo batch UUID 的无损 URL-safe Base64 短编码和行序号，使各租户 demo 副本共存。
- 租户内唯一：`DemoDataBatch.batch_code`、`OperationTask.idempotency_key`。保留原有业务键，同租户重复导入仍返回同一 active batch 和同一张业务图。
- 父链唯一：publish slot、playlist、work order、operation package 和 production node run 的唯一键均包含租户所属父实体 ID，不需要额外 tenant 维度。

## TDD 与验证证据

- RED：先新增 A/B 同请求端到端导入测试；首次在 tenant B 失败，`UNIQUE constraint failed: channels.youtube_channel_id`。
- GREEN：单条回归 `1 passed in 0.54s`。测试还验证同租户重复导入幂等、A/B 只见各自完整 channel/drama/schedule/task/work-order/package/video 图，以及四个全局唯一约束仍存在。
- Task 9 focused + demo：`59 passed, 1 warning in 1.70s`。warning 是已知 Starlette/httpx 弃用警告。
- Full backend：`1091 passed, 4 failed, 1 warning in 32.38s`。四个失败均来自同时进行的 Task 10 `settings` / `audit` 共享工作树改动；本修复未修改该范围，由主控在 Task 10 提交后统一复跑 full backend。

## 交付边界

- 未写入任何业务数据库，未调用外部服务。
- 未 push、merge、deploy，不声明生产或业务验收完成。
