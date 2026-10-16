# V14 Local Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从智矩已有工单运行 V14，在当前 Mac 调用 Codex，云端保存输入、断点和完整文本运营包。

**Architecture:** 新增固定 V14 运行记录和阶段回传接口，不启动原有飞书批处理入口。本机出站领取任务，只把模型当作结构化内容函数；既有六节点和运营包页面继续承载结果。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Alembic、现有原生 JavaScript 页面、Codex CLI。

**Spec:** `docs/superpowers/specs/2026-10-17-v14-local-executor-design.md`

## Global Constraints

- 现有飞书同步内容、流程、字段映射及“任务／工单”叫法全部保持原样。
- 先接通 V14，不建设多版本管理，不迁移旧本地批次，不修改当前运营 Skills 的生产配置。
- 云端保存配置、输入、断点、完整 JSON、证据与创意历史；本机仅执行和缓存，登录凭据不上传。
- 固定模型，不可用时明确失败，不能静默换模型；不以桌面登录推定 CLI 可用。
- 不自动生图、不自动发布视频、不自动回写飞书。
- 新运行的 `text_ready` 表示文本完成；既有运营包合并后的 `review_pending` 保持不变。两者分别展示，不能把既有审核状态改成已交付。
- 当前分支 `feature/tencent-cloud-deployment`，计划基线 `858a0b2`；不切换 dev、不合并、不部署。
- 每项执行前重查工作区和相关 AGENTS，保留其他人的修改；测试不得连接生产库。

## Review Focus

1. 飞书导入的运营包已有结果：拒绝自动覆盖，提示使用未生产工单；在任务 1 测试。
2. 一次结果已落库但响应丢失：重传返回同一接受结果，不再生成、不重复展示；在任务 2、4 测试。
3. 切换公司或登录过期：停止领取，不能将另一公司的任务发给原主机；在任务 2、4 测试。
4. 频道缺少 V14 规则、剧情字段或资产：模型调用前报告具体缺项，不退回旧本地目录猜测；在任务 3 测试。
5. 六节点完成后现有审核状态与文本完成不同：保留 `review_pending`，页面不显示图片或交付已完成；在任务 5 测试。

## 文件职责

- 新增 `backend/zhiju/models/v14.py`、`schemas/v14.py`：公司执行配置、固定 V14 规则内容、运行快照、阶段尝试及完整结果契约。
- 新增 `backend/zhiju/services/v14_runs.py`：创建、领取、阶段接受、历史和恢复；`v14_outputs.py`：V14 JSON 到现有运营包字段映射。
- 新增 `backend/zhiju/api/v14.py`：复用现有登录与租户权限的接口；在 `app.py` 注册。
- 新增 `backend/zhiju/v14_runtime/`：从当前 V14 提取的规则、结构定义、提示词构建及硬校验，不含飞书和批次状态操作。
- 新增 `backend/zhiju/v14_executor/`：CLI 模型客户端、云端客户端及单工单执行循环；入口 `python -m zhiju.v14_executor`。
- 修改 `models/__init__.py`、`tenant_scope.py`、新增 Alembic revision：注册模型及租户范围。
- 修改 `assets/app.js`、`assets/styles.css`、`index.html`：设置、工单运行入口和状态；不重构既有页面。
- 新增 `backend/tests/test_v14_{runs,api,contract,outputs,executor,frontend}.py` 及 `docs/v14-executor.md`。

## 接口约定

复用当前 `Principal`、`get_tenant_db`、设备与公司权限，不创建第二套身份系统。首期执行器使用操作者明确配置的现有智矩登录会话，本地保存，不进入日志、快照或源码；过期需重新登录，不绕过认证。云端还要校验设置中绑定的主机与当前会话设备相同。

- `GET/PUT /api/v3/v14/settings`：`host_id, account_profile, default_model, available_models, rules, channel_inputs`。模型能力由本机上报，规则/频道材料由设置上传并保存在云端；配置正文不含凭据。
- `POST /api/v3/work-orders/{id}/v14-runs`：创建或返回该工单活动运行，固定配置快照；已有已接受产物拒绝覆盖。
- `GET /api/v3/work-orders/{id}/v14-runs/current`：状态、节点、错误、停止确认及当前运行 ID。
- `POST /api/v3/v14/claims`：以 `host_id` 领取一个运行，返回 `RunEnvelope`，无工作返回 204。
- `POST /api/v3/v14/runs/{id}/attempts`：`node_type, claim_id`，创建并保存调用前的 `attempt_id`。
- `PUT /api/v3/v14/runs/{id}/attempts/{attempt_id}`：`claim_id, outcome, result, error`；outcome 为 accepted/content_error/system_error。接受操作保存完整结果并更新既有输出和节点。
- `POST /api/v3/v14/runs/{id}/heartbeat`、`/cancel`、`/resume`；resume 要求原尝试已停止确认，过期回传拒绝。三次内容失败进入 `needs_user_review`，普通 resume 不重置次数。

`RunEnvelope` 固定字段：`run_id, work_order_id, package_id, tenant_id, host_id, claim_id, model, input_snapshot, rules_snapshot, accepted_results, creative_history, retry_state`。每项结果含 `node_type, attempt_id, payload`；云端 ID 为唯一业务身份。

### Task 1: 云端运行记录和快照

**Files:** `models/v14.py`, `schemas/v14.py`, `services/v14_runs.py`, `models/__init__.py`, `tenant_scope.py`, 新迁移及 `backend/tests/test_v14_runs.py`。

**Interfaces:** 提供 `create_run(session: Session, work_order_id: str) -> V14Run`、`get_run(session: Session, run_id: str) -> V14Run`，返回具有上述快照字段的租户归属记录。

- [ ] 写失败测试：`test_create_run_freezes_inputs` 断言修改设置后旧快照不变；`test_existing_imported_outputs_are_not_overwritten` 断言拒绝覆盖；`test_tenant_cannot_read_other_run` 断言另一公司不可读。
- [ ] 运行 `uv run pytest backend/tests/test_v14_runs.py -q`，确认因未实现失败。
- [ ] 实现模型和增量迁移：设置每公司一条；运行关联真实工单、运营包，活动运行不能重复；阶段尝试保留完整 JSON、错误类型、内容尝试序号与运行归属。迁移不修改既有同步记录。
- [ ] 同一命令通过，并测试迁移升级/降级只涉及新表；使用现有测试夹具，不访问生产数据库。
- [ ] 定向提交：`feat: persist V14 execution snapshots and attempts`。

### Task 2: 领取、回传和恢复协议

**Files:** `services/v14_runs.py`, `api/v14.py`, `app.py`, `backend/tests/test_v14_api.py`。

**Interfaces:** 提供 `claim_run(session, host_id: str) -> RunEnvelope | None`、`begin_attempt(session, run_id: str, claim_id: str, node_type: str) -> V14Attempt`、`submit_attempt(session, run_id: str, attempt_id: str, payload: AttemptSubmission) -> RunRead`；实现上文端点。

- [ ] 写失败测试：`test_claim_requires_bound_device`、`test_company_switch_cannot_claim`、`test_duplicate_submission_is_idempotent`、`test_stale_attempt_cannot_overwrite`、`test_disconnect_never_reassigns_automatically`、`test_cancel_blocks_late_results`。
- [ ] 运行 `uv run pytest backend/tests/test_v14_api.py -q` 确认失败。
- [ ] 用数据库事务和行锁处理领取及接受；回传与节点推进同一事务。既有 production/package_outputs 写入函数内部有 commit，必须提供供 V14 调用的无提交路径，原接口仍按原方式提交。主机 90 秒无心跳显示中断，但不自动重新领取。每 15 秒心跳；resume 必须确认旧进程停止并使旧 claim 失效。
- [ ] 同一测试通过；内容失败第三次停止，系统错误不消耗内容重试；保留反馈和已接受阶段。
- [ ] 定向提交：`feat: add tenant-scoped V14 execution protocol`。

### Task 3: 提取固定 V14 内容契约与结果适配

**Files:** `v14_runtime/{contract,prompts,validators,market}.py`、规则资源文件、`services/v14_outputs.py`、`backend/tests/test_v14_contract.py`、`test_v14_outputs.py`。

**Interfaces:** `build_stage_input(envelope: RunEnvelope, node_type: str) -> StageInput`；`validate_result(stage: StageInput, result: dict, history: list[dict]) -> list[str]`；`apply_outputs(session: Session, run: V14Run, attempt: V14Attempt, result: dict) -> None`。StageInput 含 prompt、schema、冻结规则与前序结果。

- [ ] 写失败测试：`test_missing_channel_rules_fail_before_model`、`test_title_only_receives_global_and_title_sections`、`test_downstream_inherits_packaging_brief`、`test_community_count_zero_one_two`、`test_full_evidence_and_json_are_retained`。
- [ ] 运行 `uv run pytest backend/tests/test_v14_contract.py backend/tests/test_v14_outputs.py -q` 确认失败。
- [ ] 只读当前 V14 的完整契约及依赖，提取提示词/结构/校验到项目内，保留来源说明。禁止导入旧控制器触发批次/飞书副作用；不从 Markdown 反向取业务数据。剧情来自云端快照；市场证据用原 V14 检索方式获取并保存原始证据，检索失败明确报系统错误。
- [ ] 实现 JSON 到现有标题、封面提示词、描述、播放列表、社群输出的映射，接受前用云端完整创意历史校验，同公司接受操作串行化；merge 复用现有渲染与审核入口。完整 JSON 是权威来源，展示字段不能替代它。
- [ ] 同一测试通过；正常 V14 样例保留包装简报及每组输出；已有运营包合同测试仍通过。
- [ ] 定向提交：`feat: adapt frozen V14 contracts to production outputs`。

### Task 4: 本机执行器与 Codex 客户端

**Files:** `v14_executor/{__main__,client,codex,runner}.py`、`backend/tests/test_v14_executor.py`、`docs/v14-executor.md`。

**Interfaces:** `CodexClient.generate(stage: StageInput, model: str) -> dict`；`run_once(client: CloudClient, model_client: CodexClient) -> bool`，无任务返回 False；CloudClient 对应任务 2 的固定接口。

- [ ] 写失败测试：`test_explicit_model_and_schema_passed`、`test_unavailable_model_has_no_fallback`、`test_network_retry_reuses_result`、`test_restart_uses_cloud_accepted_stages`、`test_expired_login_stops_claims`、`test_timeout_stops_child_before_resume`。
- [ ] 运行 `uv run pytest backend/tests/test_v14_executor.py -q` 确认失败。
- [ ] 只读本机 CLI 帮助和登录状态确认受支持参数；通过结构化参数调用 `codex exec`，显式模型、只读沙箱、临时目录和 JSON schema，禁止 shell 拼接。CLI 不支持可靠列举时，设置仅展示操作者配置且通过实际调用验证的模型，不伪造可用列表。
- [ ] 实现出站客户端及单工单循环；调用前保存尝试，回传失败仅重传缓存结果；恢复读取云端状态。模型超时终止子进程，不能把仍在运行的进程当作已停。文档给出前台及 macOS 用户级常驻运行方式，不自动安装服务。
- [ ] 同一测试通过，所有 Codex/检索/云端调用使用替身；测试不得使用当前真实账号生成内容。
- [ ] 定向提交：`feat: run V14 stages through local Codex executor`。

### Task 5: 设置、工单入口及端到端验收

**Files:** `assets/app.js`, `assets/styles.css`, `index.html`, `backend/tests/test_v14_frontend.py`, `test_v14_api.py`, `docs/v14-executor.md`。

**Interfaces:** 页面消费任务 2 的设置/运行接口，工单详情操作为运行、取消、继续，展示主机、模型、阶段、错误与文本完成状态；原工单和运营包 ID 不变。

- [ ] 写失败测试：`test_run_button_posts_current_work_order_id`、`test_completed_text_keeps_review_pending`、`test_missing_configuration_shows_actionable_error`、`test_six_stages_reach_existing_package_view`。
- [ ] 运行 `uv run pytest backend/tests/test_v14_frontend.py backend/tests/test_v14_api.py -q` 确认失败。
- [ ] 实现设置绑定、规则/频道材料上传和运行 UI，延用当前抽屉与颜色；“继续”不得自动开启新的三次内容重试。缺配置时阻止启动并展示缺项，不显示假运行进度。
- [ ] 运行全部新增 V14 测试、`test_production_contract.py`、`test_production_tenant_isolation.py` 和对应现有飞书同步合同测试；前端用现有 DOM 测试方式验证实际按钮请求和回显。失败只修本次回归。
- [ ] 定向提交：`feat: expose V14 execution controls in Zhiju`。
- [ ] 记录代码与替身验收结果；真实模型验收仍需选定测试工单和模型。经用户授权后再安装本机执行器、执行单工单并从页面回读；该验收前不能宣称 V14 业务跑通。合并、部署另外交接。

## 计划自审结论

范围覆盖：云端配置/快照/历史（任务 1、3）、运行权限与恢复（任务 2、4）、六阶段及现有运营包（任务 3、5）、模型可选与本机账号（任务 4、5）。现有合并会进入 `review_pending`，因此明确保留该状态，另用 V14 运行的 `text_ready` 表达文本完成，不改旧业务语义。首期不引入多版本平台、远程任意命令或新的账号体系。
