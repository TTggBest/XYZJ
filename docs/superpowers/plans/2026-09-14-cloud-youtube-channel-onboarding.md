# Cloud YouTube Channel Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在腾讯云部署中提供先 Google 授权、自动发现并多选导入 YouTube 频道的完整流程，同时保持 Studio 本地频道与 OAuth 流程不变。

**Architecture:** 云端通过 Google Web OAuth 回调创建一次性导入会话，将 OAuth token 以服务端密钥加密后保存，并把 YouTube API 返回的非敏感频道资料保存为短期候选快照。用户为候选频道补充目标市场和默认题材后，以单个事务创建频道、Google 账号、授权关系及审计事件；本地部署仍使用现有 macOS Keychain 路径。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MySQL、Pydantic 2、原生 JavaScript、pytest、Google OAuth 2.0、YouTube Data API v3、cryptography/Fernet

**Spec:** `docs/superpowers/specs/2026-09-14-cloud-youtube-channel-onboarding-design.md`

## Global Constraints

- 腾讯云只允许使用 `zhiju_cloud`，不得连接、迁移或修改 Studio 的 `zhiju_prod`、`zhiju_dev`。
- Studio 本地部署的现有手工建频道、macOS Keychain 和本机 OAuth 回调必须保持不变。
- OAuth Client Secret、refresh token、access token 和令牌加密密钥不得写入 Git、日志、API 响应或数据库明文字段。
- 云端 OAuth 回调固定为 `https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback`。
- 同一 YouTube Channel ID 只能绑定一个公司；冲突响应不得泄露已有公司的身份。
- 云端新增频道必须使用授权导入，不创建 OAuth 前的频道占位记录。
- 一个 Google 账号发现多个 YouTube 频道时必须支持多选，并在一个事务内完成整批导入。
- 国家代码来自标准国家目录；推荐语言和时区允许用户修改。

---

### Task 1: 云端 OAuth 配置与国家目录

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/zhiju/config.py`
- Create: `backend/zhiju/services/country_catalog.py`
- Test: `backend/tests/test_cloud_youtube_config.py`
- Test: `backend/tests/test_country_catalog.py`

**Interfaces:**
- Produces: `Settings.youtube_oauth_client_id: str`、`youtube_oauth_client_secret: str`、`youtube_oauth_redirect_uri: str`、`oauth_encryption_key: str`
- Produces: `CountryOption(code: str, name_zh: str, recommended_language: str, recommended_timezone: str, timezones: tuple[str, ...])`
- Produces: `list_country_options() -> list[CountryOption]` 与 `get_country_option(code: str) -> CountryOption`

- [ ] **Step 1: 写配置失败测试**

```python
def test_cloud_oauth_config_is_redacted_and_uses_https_callback(monkeypatch):
    settings = make_cloud_settings(
        youtube_oauth_client_id="client-id",
        youtube_oauth_client_secret="client-secret",
        oauth_encryption_key=Fernet.generate_key().decode(),
    )
    assert settings.youtube_oauth_redirect_uri == (
        "https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback"
    )
    assert "client-secret" not in settings.youtube_oauth_public_status()
```

- [ ] **Step 2: 运行配置测试并确认因字段和依赖不存在而失败**

Run: `.venv/bin/pytest backend/tests/test_cloud_youtube_config.py -q`

Expected: FAIL，提示 OAuth 配置字段或 `cryptography` 不存在。

- [ ] **Step 3: 添加依赖和严格配置字段**

```python
youtube_oauth_client_id: str = ""
youtube_oauth_client_secret: str = ""
youtube_oauth_redirect_uri: str = (
    "https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback"
)
oauth_encryption_key: str = ""
```

云端允许服务在 OAuth 未配置时启动，但状态接口必须报告 `configured=false`；只有开始授权时才返回中文配置错误。

- [ ] **Step 4: 写国家目录失败测试**

```python
def test_country_catalog_returns_exact_code_and_editable_recommendations():
    us = get_country_option("us")
    assert us.code == "US"
    assert us.name_zh == "美国"
    assert us.recommended_language == "en"
    assert "America/New_York" in us.timezones

def test_country_catalog_rejects_unknown_code():
    with pytest.raises(ValueError, match="国家或地区代码无效"):
        get_country_option("XX")
```

- [ ] **Step 5: 实现版本化国家目录**

目录覆盖系统当前支持的中国、美国、印度尼西亚、菲律宾、巴西、西班牙语市场、土耳其、阿拉伯语市场、孟加拉等实际运营国家；API 输出固定按中文名排序。选择只接受 ISO alpha-2 code，后端根据 code 回填中文名。

- [ ] **Step 6: 运行测试并提交**

Run: `.venv/bin/pytest backend/tests/test_cloud_youtube_config.py backend/tests/test_country_catalog.py -q`

Expected: PASS。

```bash
git add pyproject.toml backend/zhiju/config.py backend/zhiju/services/country_catalog.py backend/tests/test_cloud_youtube_config.py backend/tests/test_country_catalog.py
git commit -m "feat: add cloud YouTube OAuth configuration"
```

### Task 2: 导入会话、候选频道与加密令牌模型

**Files:**
- Modify: `backend/zhiju/models/integration.py`
- Modify: `backend/zhiju/models/__init__.py`
- Create: `backend/alembic/versions/0d7a4c9e12f6_add_youtube_channel_import_sessions.py`
- Create: `backend/zhiju/services/oauth_secret_store.py`
- Test: `backend/tests/test_cloud_oauth_secret_store.py`
- Test: `backend/tests/test_youtube_channel_import_models.py`
- Test: `backend/tests/test_tenant_relational_constraints.py`

**Interfaces:**
- Produces: `YouTubeChannelImportSession`、`YouTubeChannelImportCandidate`、`OAuthTokenSecret`
- Produces: `EncryptedDatabaseSecretStore(session: Session, key: str)` with `put(grant_id: str, token: Mapping[str, object]) -> str`、`get(grant_id: str) -> dict[str, object] | None`、`delete(grant_id: str) -> None`

- [ ] **Step 1: 写模型与密文存储失败测试**

```python
def test_database_secret_store_never_persists_plaintext(session, fernet_key):
    store = EncryptedDatabaseSecretStore(session, fernet_key)
    ref = store.put("grant-a", {"access_token": "access-secret", "refresh_token": "refresh-secret"})
    row = session.scalar(select(OAuthTokenSecret))
    assert ref == "db-encrypted://google-oauth/grant-a"
    assert "access-secret" not in row.encrypted_payload
    assert "refresh-secret" not in row.encrypted_payload
    assert store.get("grant-a")["refresh_token"] == "refresh-secret"
```

```python
def test_import_session_and_candidate_are_tenant_owned(session):
    import_session = YouTubeChannelImportSession(
        tenant_id="tenant-a", user_id="user-a", auth_session_id="session-a",
        opaque_state="state-a", status="pending_oauth", expires_at=FUTURE,
    )
    session.add(import_session)
    session.flush()
    session.add(YouTubeChannelImportCandidate(
        tenant_id="tenant-b", import_session_id=import_session.id,
        youtube_channel_id="UC-a", title="A",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: 运行测试并确认模型不存在而失败**

Run: `.venv/bin/pytest backend/tests/test_cloud_oauth_secret_store.py backend/tests/test_youtube_channel_import_models.py -q`

Expected: collection FAIL，提示新模型或存储类不存在。

- [ ] **Step 3: 添加三张表和复合租户外键**

`youtube_channel_import_sessions` 保存发起人、认证会话、grant、一次性 state、状态和过期时间；`youtube_channel_import_candidates` 保存 YouTube 非敏感快照；`oauth_token_secrets` 以 grant 为唯一键保存 Fernet 密文。迁移的 `down_revision` 使用执行时检测到的唯一 Alembic head。

- [ ] **Step 4: 实现 Fernet 密文存储**

```python
class EncryptedDatabaseSecretStore:
    def put(self, grant_id: str, token: Mapping[str, object]) -> str:
        payload = json.dumps(dict(token), separators=(",", ":"), sort_keys=True)
        encrypted = self._fernet.encrypt(payload.encode()).decode()
        # upsert OAuthTokenSecret; never log payload
        return f"db-encrypted://google-oauth/{grant_id}"
```

- [ ] **Step 5: 运行模型、密文和租户关系测试**

Run: `.venv/bin/pytest backend/tests/test_cloud_oauth_secret_store.py backend/tests/test_youtube_channel_import_models.py backend/tests/test_tenant_relational_constraints.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/zhiju/models backend/zhiju/services/oauth_secret_store.py backend/alembic/versions backend/tests/test_cloud_oauth_secret_store.py backend/tests/test_youtube_channel_import_models.py backend/tests/test_tenant_relational_constraints.py
git commit -m "feat: persist encrypted cloud OAuth imports"
```

### Task 3: YouTube 频道发现和事务导入服务

**Files:**
- Modify: `backend/zhiju/services/youtube_oauth.py`
- Create: `backend/zhiju/services/youtube_channel_import.py`
- Test: `backend/tests/test_youtube_oauth_service.py`
- Create: `backend/tests/test_youtube_channel_import_service.py`

**Interfaces:**
- Consumes: `CountryOption`、`EncryptedDatabaseSecretStore` 和 Task 2 三个模型
- Produces: `create_channel_import_state(session, principal, ttl_seconds=600) -> str`
- Produces: `complete_channel_import_oauth(session, secret_store, state, identity, token, youtube_payload) -> str`
- Produces: `get_channel_import(session, principal, import_session_id) -> dict[str, object]`
- Produces: `commit_channel_import(session, principal, import_session_id, selections: list[ChannelImportSelection]) -> list[Channel]`
- Produces: `parse_youtube_channel_candidates(payload: Mapping[str, object]) -> list[dict[str, object]]`

- [ ] **Step 1: 扩充 YouTube 响应解析失败测试**

```python
def test_fetch_channels_requests_all_import_parts(monkeypatch):
    fetch_youtube_channels("access")
    assert "part=id%2Csnippet%2CcontentDetails%2CbrandingSettings" in requested_url

def test_parse_candidates_keeps_every_managed_channel():
    rows = parse_youtube_channel_candidates(multi_channel_payload())
    assert [row["youtube_channel_id"] for row in rows] == ["UC-one", "UC-two"]
    assert rows[0]["uploads_playlist_id"] == "UU-one"
```

- [ ] **Step 2: 运行解析测试并确认失败**

Run: `.venv/bin/pytest backend/tests/test_youtube_oauth_service.py -q`

Expected: FAIL，因为请求仍只有 `id,snippet` 且不存在候选解析器。

- [ ] **Step 3: 实现完整发现和导入状态转换**

回调完成时必须：消费一次性 state；创建或复用当前租户 GoogleAccount/OAuthGrant；保留已有 refresh token；加密保存 token；保存所有候选快照；把会话改为 `ready`。0 个频道返回中文业务错误，不能创建 Channel。

- [ ] **Step 4: 写事务导入失败测试**

```python
def test_multi_select_import_is_atomic(session, principal, ready_import):
    session.add(existing_channel("UC-two"))
    with pytest.raises(ConflictError, match="频道已被绑定"):
        commit_channel_import(session, principal, ready_import.id, [
            selection("UC-one", "US", "爱情"),
            selection("UC-two", "BR", "家庭"),
        ])
    assert session.scalar(select(func.count(Channel.id))) == 1

def test_import_uses_catalog_country_and_youtube_identity(session, principal, ready_import):
    channels = commit_channel_import(
        session, principal, ready_import.id, [selection("UC-one", "US", "爱情")]
    )
    assert channels[0].original_name == "Actual One"
    assert channels[0].country_code == "US"
    assert channels[0].country_name_zh == "美国"
    assert channels[0].status == "authorized"
```

- [ ] **Step 5: 实现提交、绑定、审计和过期清理**

在任何写入前检查全部候选、国家代码、租户、权限、会话状态和重复 Channel ID；随后一次 commit 创建所有 Channel 和 AccountChannelAuthorization。过期且未绑定的会话由 `cleanup_expired_channel_imports(session, now) -> int` 删除候选、未使用 grant 及密文。

- [ ] **Step 6: 运行服务测试并提交**

Run: `.venv/bin/pytest backend/tests/test_youtube_oauth_service.py backend/tests/test_youtube_channel_import_service.py -q`

Expected: PASS。

```bash
git add backend/zhiju/services/youtube_oauth.py backend/zhiju/services/youtube_channel_import.py backend/tests/test_youtube_oauth_service.py backend/tests/test_youtube_channel_import_service.py
git commit -m "feat: discover and import YouTube channels"
```

### Task 4: 云端授权导入 API

**Files:**
- Modify: `backend/zhiju/schemas/youtube_oauth.py`
- Modify: `backend/zhiju/api/youtube_oauth.py`
- Test: `backend/tests/test_youtube_route_access.py`
- Create: `backend/tests/test_youtube_channel_import_api.py`
- Modify: `backend/tests/test_youtube_tenant_isolation.py`

**Interfaces:**
- Consumes: Task 3 service functions
- Produces: `POST /api/v3/youtube/channel-imports/start`
- Produces: `GET /api/v3/youtube/oauth/callback`
- Produces: `GET /api/v3/youtube/channel-imports/{session_id}`
- Produces: `POST /api/v3/youtube/channel-imports/{session_id}/commit`
- Produces: cloud-capable `GET /api/v3/settings/youtube-oauth`

- [ ] **Step 1: 写 API 路由失败测试**

```python
def test_cloud_start_returns_web_authorization_url(client, cloud_settings):
    response = client.post("/api/v3/youtube/channel-imports/start")
    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://accounts.google.com/")

def test_import_detail_never_returns_tokens(client, ready_import):
    body = client.get(f"/api/v3/youtube/channel-imports/{ready_import.id}").json()
    assert "access_token" not in json.dumps(body)
    assert "refresh_token" not in json.dumps(body)
```

- [ ] **Step 2: 运行 API 测试并确认 404 或 501**

Run: `.venv/bin/pytest backend/tests/test_youtube_channel_import_api.py backend/tests/test_youtube_route_access.py -q`

Expected: FAIL，云端入口尚不存在或被 `_require_macos_capability()` 拒绝。

- [ ] **Step 3: 添加 Pydantic 请求响应和云端路由**

```python
class ChannelImportSelection(BaseModel):
    candidate_id: str
    operational_name: str | None = None
    target_country_code: str = Field(min_length=2, max_length=2)
    default_genre: str = Field(min_length=1, max_length=120)
    default_language: str | None = Field(default=None, max_length=20)
    timezone: str | None = Field(default=None, max_length=64)

class ChannelImportCommit(BaseModel):
    selections: list[ChannelImportSelection] = Field(min_length=1)
```

回调根据 `Settings.deployment` 选择云端导入路径或既有本地频道授权路径；不得删除本地实现。

- [ ] **Step 4: 添加权限和租户隔离测试**

覆盖未登录 401、只读账号 403、跨租户 404、超级管理员未选公司 409、同租户负责人成功，以及回调 state 与当前会话不一致失败。

- [ ] **Step 5: 运行路由和隔离测试并提交**

Run: `.venv/bin/pytest backend/tests/test_youtube_channel_import_api.py backend/tests/test_youtube_route_access.py backend/tests/test_youtube_tenant_isolation.py -q`

Expected: PASS。

```bash
git add backend/zhiju/schemas/youtube_oauth.py backend/zhiju/api/youtube_oauth.py backend/tests/test_youtube_channel_import_api.py backend/tests/test_youtube_route_access.py backend/tests/test_youtube_tenant_isolation.py
git commit -m "feat: expose cloud YouTube import API"
```

### Task 5: 云端频道授权导入向导

**Files:**
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Modify: `backend/tests/frontend_dom_harness.js`
- Modify: `backend/tests/test_auth_frontend_contract.py`
- Create: `backend/tests/test_youtube_channel_import_frontend.py`

**Interfaces:**
- Consumes: Task 4 API
- Produces: `openYouTubeChannelImport()`、`renderYouTubeImportCandidates(importSession)`、`countrySelectOptions(selectedCode)`
- Produces: browser message handler for `youtube-channel-import-ready` and `youtube-channel-import-failed`

- [ ] **Step 1: 写前端契约失败测试**

```python
def test_cloud_channel_button_starts_oauth_import():
    source = APP_JS.read_text()
    assert "授权并导入 YouTube 频道" in source
    assert 'api("/youtube/channel-imports/start"' in source

def test_country_code_is_not_a_free_text_field():
    source = APP_JS.read_text()
    assert 'name="target_country_code"' in source
    assert '<select' in source
```

- [ ] **Step 2: 运行测试并确认旧手工表单导致失败**

Run: `.venv/bin/pytest backend/tests/test_youtube_channel_import_frontend.py -q`

Expected: FAIL，按钮仍为“新增频道”，国家代码仍为文本输入。

- [ ] **Step 3: 实现云端四步向导**

云端按钮打开 OAuth 弹窗；回调 `postMessage` 后获取导入会话；候选列表展示头像、名称、Channel ID 并允许多选；下一步为每个频道生成目标市场 select、默认题材、运营简称、语言和时区；提交成功后关闭弹窗并刷新频道列表。

- [ ] **Step 4: 保留本地手工入口并处理错误**

`deployment === "local"` 时仍打开原 `channelForm()`；云端未配置 OAuth 时只禁用导入按钮并显示中文原因，频道列表本身继续加载。OAuth 取消、0 频道、重复绑定和网络失败均在向导内显示，不替换整页。

- [ ] **Step 5: 运行 DOM/契约测试并提交**

Run: `.venv/bin/pytest backend/tests/test_youtube_channel_import_frontend.py backend/tests/test_auth_frontend_contract.py -q`

Expected: PASS。

```bash
git add assets/app.js assets/styles.css backend/tests/frontend_dom_harness.js backend/tests/test_auth_frontend_contract.py backend/tests/test_youtube_channel_import_frontend.py
git commit -m "feat: add YouTube channel import wizard"
```

### Task 6: 迁移、回归与云端部署准备

**Files:**
- Modify: `deploy/tencent-cloud/README.md`
- Modify: `deploy/tencent-cloud/zhiju-app.env.example`
- Modify: `docs/superpowers/specs/2026-09-14-cloud-youtube-channel-onboarding-design.md`

**Interfaces:**
- Consumes: Tasks 1-5 completed branch
- Produces: repeatable cloud configuration and deployment instructions

- [ ] **Step 1: 运行迁移图检查**

Run: `.venv/bin/alembic -c backend/alembic.ini heads`

Expected: exactly one head，且为 Task 2 新迁移。

- [ ] **Step 2: 在隔离 MySQL 测试库执行升级和降级/升级**

Run: `ZHJ_DATABASE_URL=<isolated-test-url> .venv/bin/alembic -c backend/alembic.ini upgrade head`

Expected: 新三张表、索引和租户复合外键创建成功；不连接 Studio 数据库。

- [ ] **Step 3: 更新云端配置文档**

文档明确 Google Console 中的 Web client 类型、正式回调 URL、四个 `ZHJ_` 环境变量、生成 Fernet key 的一次性命令，以及“不得提交真实值”。示例环境文件只使用占位值。

- [ ] **Step 4: 运行定向测试**

Run: `.venv/bin/pytest backend/tests/test_cloud_youtube_config.py backend/tests/test_country_catalog.py backend/tests/test_cloud_oauth_secret_store.py backend/tests/test_youtube_channel_import_models.py backend/tests/test_youtube_oauth_service.py backend/tests/test_youtube_channel_import_service.py backend/tests/test_youtube_channel_import_api.py backend/tests/test_youtube_route_access.py backend/tests/test_youtube_tenant_isolation.py backend/tests/test_youtube_channel_import_frontend.py -q`

Expected: PASS。

- [ ] **Step 5: 运行全量回归**

Run: `.venv/bin/pytest -q`

Expected: 全量 PASS，且 Studio 既有 OAuth、频道和前端契约测试没有回归。

- [ ] **Step 6: 提交部署准备**

```bash
git add deploy/tencent-cloud docs/superpowers/specs/2026-09-14-cloud-youtube-channel-onboarding-design.md
git commit -m "docs: configure cloud YouTube OAuth deployment"
```

- [ ] **Step 7: 部署前人工门槛**

只有在腾讯云环境已经取得真实 Google Web OAuth Client ID、Client Secret 和新生成的 Fernet key 后才部署。部署时先备份 `zhiju_cloud`，再迁移和切换 release；不得复用或展示聊天中、Git 中或 Studio 本地 Keychain 中的敏感值。

- [ ] **Step 8: 云端业务验收**

使用真实测试 Google 账号完成一次授权、多频道选择、目标市场联动、批量导入和刷新令牌验证。只有这些真实操作通过后，才能声明云端 YouTube 授权导入业务验收完成。
