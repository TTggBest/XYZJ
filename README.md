# 筱宇智矩 V3

本目录正在从 SQLite/文件状态驱动的旧管理系统迁移为 MySQL 唯一真相源的模块化服务。

## 本机开发环境

- Web/API：`http://127.0.0.1:19732`
- API 文档：`http://127.0.0.1:19732/docs`

## 多设备实时状态

智矩使用 SSE 通知多台设备刷新共用 MySQL 中的最新状态，不做定时轮询。

- 生产运行包每次启动时按本机 hostname 查询 `devices` 表，自动取得 `builder`、`studio` 或 `worker` 角色。
- Studio 自动监听 `0.0.0.0` 并作为 SSE 中心；其他生产设备自动使用 `http://192.168.8.8:19732`。
- 本机开发：`ZHJ_DEVICE_ROLE=builder`，`ZHJ_REALTIME_HUB_URL` 留空。

SSE 只发送变更通知，页面收到后仍通过本机 API 从 MySQL 读取业务数据。
- 智矩 MySQL：`127.0.0.1:33306`
- 数据库：`zhiju_dev`
- 配置：`.env`，不进入版本管理

智矩的 MySQL 使用独立端口、数据目录和 socket，不连接或修改智核使用的 3306 实例。

## 初始化与运行

```bash
cd 管理系统
uv sync --dev
./scripts/mysql_dev.sh start
.venv/bin/alembic upgrade head
.venv/bin/python run_v3.py
```

桌面启动器 `launcher.py` 会先确保智矩 MySQL 已启动，再启动 V3 服务。

## 数据库操作

```bash
./scripts/mysql_dev.sh status
./scripts/mysql_dev.sh stop
.venv/bin/alembic current
.venv/bin/alembic check
.venv/bin/alembic upgrade head
```

运行账号 `zhiju_app` 只有业务增删改查权限；迁移账号 `zhiju_migrator` 才有 DDL 权限。OAuth Token、密码和第三方密钥禁止写入业务表，数据库只保存 `credential_ref`。

## 当前 V3 模块

- MySQL 配置、连接池与 Alembic migrations
- 设备、Google 主账号、OAuth Grant 引用
- YouTube 频道稳定身份
- 频道生命周期、暂停、归档和保留历史的软删除
- 频道身份、授权账号、头像、DNA、分析和同步状态聚合主档
- 账号与频道授权关系、授权事件
- OAuth Grant、scope、Secret引用和频道绑定校验 API
- 审计事件和字段中文备注
- 账号、频道、设备基础 API
- 频道档案、头像和 Banner 资产引用
- 频道关键词与标签明细
- 频道默认置顶评论模板、语言版本和生效历史
- 频道分析报告历史版本、题材/关键词评分、用户画像、策略建议和数据库证据
- Channel DNA 版本
- DNA 高低表现关键词、剧情模式信号
- 第三方集成账号与 Secret 引用
- 第三方集成、账号、凭证引用和连接验证 API
- 本地剧库、独立别名、核心词和语言可用性
- 剧目目标语言翻译与素材可用矩阵
- 包含缺失组合的动态剧目翻译矩阵总览
- 频道播放列表与当地发布时间档位
- Community固定当地时间或相对视频档位延迟的发布时间规则
- 固化当地、北京和 UTC 时间的频道排期
- 排期幂等、档位冲突约束和状态变更历史
- 排期主选、备选、安全替换和任务生成后的冻结保护
- 排期频道、剧目、档位、候选剧和任务下发状态聚合视图
- 今日任务生成、筛选与幂等下发
- 任务频道、剧目、档期、播放列表和下发后生产进度聚合视图
- 任务下发后自动创建生产工单和运营包
- 生产工单频道、剧目、运营包、六节点和总进度聚合视图
- 搜索、标题、封面、说明、社群、合并六节点顺序执行
- 合并完成后统一审核，支持按单节点保留历史重跑
- 标题、封面、说明、社群、播放列表、检测结果和导出物的结构化表
- 运营包对历史运营包的相似度结果、幂等更新和失败合并门禁
- MD/JSON 仅作为数据库派生运营包，不承载业务状态
- YouTube视频登记、发布状态和不可变状态历史
- 运营包、排期与真实YouTube视频的事务化发布回写
- YouTube视频实际播放列表归属、当前排序评分和不可变重排历史
- 评论、推荐回复及评论回复版本
- 评论分析保留、回复审核、发布队列和结果回写状态机
- 频道和视频每日Analytics历史快照
- 国家、设备、流量来源等Analytics维度数据
- 按 `channel_id + data_type` 隔离的同步水位与工作器租约
- YouTube API请求日志和配额消耗明细
- YouTube API请求幂等账本和按日期、频道、账号、端点配额汇总
- 数据库化Skill稳定定义、双语正文和不可变版本历史
- 素材用途、文件元数据、状态流转、引用保护和软删除
- 系统事件、审计、任务、排期和视频状态历史查询

生产链路 API 位于 `/api/v3/tasks`、`/api/v3/work-orders` 和
`/api/v3/packages`。节点执行过程中没有人工审核；只有 `merge` 完成后的运营包进入
`review_pending`，最终审核退回后可以只重跑指定节点，再重新执行合并。

生产台列表使用 `/api/v3/work-orders/overview`。该接口从工单、频道、剧库、运营包和节点
尝试表实时聚合，每个节点只展示最新尝试，同时返回当前节点、完成节点数和总进度；聚合
结果不另存为业务状态，节点重试历史仍保留在 `production_node_runs`。

任务列表使用 `/api/v3/tasks/overview`。未下发任务只返回任务及计划信息；下发后同一行
附加工单、运营包和六节点实时进度。接口支持日期、频道、任务状态和任务来源筛选，不使用
页面缓存或文件状态推断下发结果。

节点产出通过 `/api/v3/packages/{package_id}/outputs/*` 写入结构化业务表。节点在本次
尝试的必要结果未落库前不能标记完成。自动检测保留全部历史，并用 `is_current` 明确
标识当前检测结论，不按文件或时间戳猜测状态。

运营包相似度通过 `/api/v3/packages/{package_id}/similarity-checks` 查询，并按对比运营包
ID 幂等写入。标题、封面、说明和整体创意评分均限制在 `0-1`；存在 `fail` 结论时禁止
合并，修正内容并重新检测为通过或警告后才可继续。

合并使用 `/api/v3/packages/{package_id}/merge`，只读取 MySQL 当前采用的数据，并在
`.runtime/artifacts/{package_id}/generation-{attempt}/` 生成 MD 和 JSON。文件路径、
SHA-256、版本和生成状态登记在 `package_artifacts`；派生文件不能反向驱动业务流程。

YouTube 回流接口位于 `/api/v3/youtube/*`。视频、评论和指标使用稳定业务键
Upsert；每日指标按日期保留历史快照。同步任务必须先领取
`channel_id + data_type` 对应的数据库租约，因此一个频道正在同步评论不会阻止其他
频道同步评论，也不会阻止同频道同步视频或Analytics。

每次真实YouTube API调用通过 `/api/v3/youtube/api-requests` 以稳定 `request_key` 登记，
请求结果与配额明细在同一事务写入。`/api/v3/youtube/quota-usage/summary` 按配额日期、频道、
Google账号和端点聚合；配额日期由调用方明确提交，不按服务器本地日期猜测。

Skill版本库位于 `/api/v3/skills`。`skills` 保存稳定代码、名称、用途和生命周期，
`skill_versions` 保存供审核的中文正文与正式执行原文。草稿可以编辑；发布后正文不可覆盖，
新版本发布会保留旧版并切换数据库当前版本标记。当前阶段不从文件导入 Skill，也不绑定任何
既有工作流；Workflow 和 Contract 在工作流边界确认后再接入。

素材中心位于 `/api/v3/media-assets`。素材通过存储提供方和对象键幂等登记，文件本体仍保存在
专用存储中，MySQL 保存哈希、MIME、尺寸、公开地址、频道、运营包和业务用途。待处理素材可
补齐文件元数据后转为可用；被频道装潢、封面或社群内容引用的素材不能归档或删除。封面和
社群节点只接受属于当前运营包、用途正确且状态为 `ready` 的图片资产。

运营包中的播放列表数据表示生产阶段的计划选择，YouTube视频播放列表归属表示发布后的
实际状态，两者不能互相覆盖。实际归属按视频和播放列表唯一，视频与播放列表必须属于同一
频道；当前位置、动态评分和来源保存在当前归属表，每次新增或重排另写不可变历史记录。

人工上传或 YouTube 同步通过 `/api/v3/youtube/videos` 回写真实视频。首次绑定运营包时，
运营包必须已通过最终审核；一个运营包只能绑定一个 YouTube 视频。绑定后普通同步即使不再
提交运营包、剧目和排期 ID，也会保留已经确认的数据库关联，不能静默清空或改绑。预约视频
会把有效排期推进为 `confirmed`，公开视频推进为 `published`，运营包推进为 `delivered`，
视频、排期和运营包状态变化分别保留历史。

频道默认置顶评论通过 `/api/v3/channels/{channel_id}/pinned-comment-templates` 管理。
模板按频道和语言独立递增版本；激活新版本时，旧的当前版本转为 `superseded` 并保留生效
区间。运营包内的置顶评论仍是该次生产采用的快照，不反向覆盖频道模板历史。

频道 Community 发布时间规则通过 `/api/v3/channels/{channel_id}/community-slots` 管理。
相对模式必须绑定同频道的有效视频发布时间档位并设置延迟分钟；固定模式只保存频道当地
时间。两种模式字段严格互斥，相同规则不能重复创建，归档规则保留历史但默认不返回。

剧目翻译通过 `/api/v3/dramas/{drama_id}/translations/{language_id}` 按剧目和语言唯一
Upsert；`/api/v3/drama-translations` 提供全局矩阵筛选。翻译就绪必须有目标语言剧名，素材
就绪必须有资源定位地址；翻译状态和素材状态的每次组合变化写入统一事件账本。

完整矩阵使用 `/api/v3/drama-translations/matrix`。接口按当前语言表动态展开每部剧的单元，
没有翻译记录的组合明确返回 `missing`，但不会为展示目的创建空业务记录；新增语言无需修改
剧库或翻译表结构。

创建排期时会自动把当前剧目登记为排名第一的主选候选；备选通过
`/api/v3/schedules/{schedule_id}/candidates` 管理。选择备选会在同一事务中更新排期剧目、
候选状态和排期变更历史。排期一旦生成任务，候选列表和当前剧目即冻结，避免工单与排期
指向不同剧目。

排期列表使用 `/api/v3/schedules/overview`，从频道、剧库、档位、播放列表、候选剧、任务
和工单实时聚合。支持日期区间、频道、排期状态及是否已生成任务筛选，候选数量和任务状态
不以页面缓存推断。

授权控制面接口位于 `/api/v3/oauth-grants`、`/api/v3/channel-authorizations/verify`
和 `/api/v3/authorization-events`。数据库和 API 只接收 `credential_ref`，禁止传入或保存
Token 明文。频道绑定仅在 Token 实际返回的 YouTube 频道 ID 与目标频道一致时生效；
不一致会保留失败事件且不会覆盖已有有效绑定。领取 YouTube 同步租约必须提交当前频道的
有效 `authorization_id`。

频道状态通过 `/api/v3/channels/{channel_id}/status` 受控变更；删除频道调用
`DELETE /api/v3/channels/{channel_id}`，实际执行软归档，不物理删除历史。归档会取消未完成
排期、任务、工单和生产节点，归档未完成运营包，并释放运行中的 YouTube 同步租约。默认
频道列表隐藏软删除记录，`include_archived=true` 可读取归档频道。

频道分析报告接口位于 `/api/v3/channels/{channel_id}/analysis-reports`。每次创建都在
频道内生成递增版本，题材评分、关键词评分、用户画像、策略建议和证据关联与报告在同一
事务落库。除人工证据外，证据实体必须已经存在于 MySQL 且属于当前频道；历史列表和
单版详情都从数据库读取，不从报告文件或页面缓存推断。

频道总览使用 `/api/v3/channels/overview`。接口聚合频道稳定身份、全部有效授权账号、当前
头像引用、Channel DNA版本、分析报告和各数据类型同步水位；支持状态、语言和归档筛选，
不会把多账号授权压成一个可能错误的主账号字段。

第三方集成接口位于 `/api/v3/integrations` 和 `/api/v3/integration-accounts/*`。
集成账号必须先登记有效且未过期的 `secret_reference`，才能通过连接验证并进入
`active` 状态；系统不接收 Bot Token、API Key 或其他密钥明文。凭证重复登记按
`integration_account_id + credential_type` 更新同一条记录，验证状态变化写入审计流水。

历史查询接口位于 `/api/v3/system-events`、`/api/v3/audit-events` 和
`/api/v3/entities/{entity_type}/{entity_id}/timeline`，支持按实体、状态、动作、操作者和
时间筛选及分页。任务、排期和 YouTube 视频另有专用历史接口。关键事件时间使用 MySQL
`DATETIME(6)`，保证同一秒内连续状态变化仍可按真实发生顺序读取。

评论同步只更新 YouTube 来源字段，不会用同步请求的默认值覆盖翻译、情绪、分析标签、
推荐回复或当前回复状态。评论分析通过 `/api/v3/youtube/comments/{comment_id}/analysis`
独立写入；回复先创建为草稿或待发布，再通过审核和状态接口进入队列。只有 YouTube
返回真实 `youtube_reply_id` 后才能标记为已发布，状态变化同步写入统一事件账本。

旧 `server.py` 暂时保留作为迁移参考，但 `launcher.py` 已不再启动它。旧 SQLite、JSON 和 `app_state` 不会作为 V3 业务状态读取。

## 验证

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q backend run_v3.py launcher.py
.venv/bin/alembic check
curl http://127.0.0.1:19732/api/health
```
