# Channel Hub Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw channel JSON drawer with an editable channel hub, add configurable channel drama types, and expose existing channel operations and analysis data without adding AI, YouTube creation, or role-management placeholders.

**Architecture:** Extend the existing FastAPI/SQLAlchemy channel-center instead of creating a parallel subsystem. MySQL remains the source of truth; resource-bearing channel fields reference existing media assets, while channel detail aggregates existing profile, keyword, playlist, pinned-comment, report, DNA, and Skill-version records.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, MySQL `zhiju_dev`, Pydantic, vanilla JavaScript, CSS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-channel-hub-design.md`

## Global Constraints

- Work only on `feature/channel-hub`; do not merge `dev`.
- Use MySQL `zhiju_dev`; do not use SQLite and do not write `zhiju_prod`.
- Reuse existing channel, Skill, playlist, media-asset, analysis-report, and DNA models.
- Do not add AI generation, YouTube playlist creation, roles, permissions, resource-path frameworks, hashes, compatibility layers, or feature flags.
- Channel name, YouTube Channel ID, and channel URL remain read-only.
- Public dramas remain independent from channels.

---

### Task 1: Configurable Channel Drama Types

**Files:**
- Create: `backend/alembic/versions/2f6c8a1d4b90_add_channel_drama_type_settings.py`
- Modify: `backend/zhiju/models/settings.py`
- Modify: `backend/zhiju/models/__init__.py`
- Modify: `backend/zhiju/schemas/settings.py`
- Modify: `backend/zhiju/services/settings.py`
- Modify: `backend/zhiju/api/settings.py`
- Modify: `assets/app.js`
- Test: `backend/tests/test_channel_drama_type_settings.py`

**Interfaces:**
- Produces: `ChannelDramaType`, `list_channel_drama_types(session, include_disabled=False)`, `create_channel_drama_type(session, payload)`, `update_channel_drama_type(session, type_id, payload)`.
- Produces API: `GET/POST /api/v3/settings/channel-drama-types`, `PUT /api/v3/settings/channel-drama-types/{type_id}`.

- [ ] **Step 1: Write failing model and route contract tests**

```python
def test_channel_drama_type_model_contract():
    columns = ChannelDramaType.__table__.columns
    assert {"code", "name", "description", "sort_order", "status"}.issubset(columns.keys())

def test_channel_drama_type_routes_are_registered():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert {"get", "post"}.issubset(paths["/api/v3/settings/channel-drama-types"])
    assert "put" in paths["/api/v3/settings/channel-drama-types/{type_id}"]
```

- [ ] **Step 2: Run the focused test and verify it fails because the model/routes do not exist**

Run: `uv run pytest backend/tests/test_channel_drama_type_settings.py -q`

- [ ] **Step 3: Add the minimal model, schemas, migration, service, and routes**

Use stable lowercase `code`, editable `name`/`description`/`sort_order`, and `status` limited to `active` or `disabled`. The migration preserves every distinct non-empty `channels.drama_type` value by creating a matching active configuration row; do not add speculative categories that are absent from current data or explicit user configuration.

- [ ] **Step 4: Add the Settings tab UI**

Add `dramaTypes` to `SETTINGS_TABS`; render a compact table and create/edit modal. Disabling a type retains existing channel values and removes it from future selection.

- [ ] **Step 5: Run focused backend and frontend checks**

Run: `uv run pytest backend/tests/test_channel_drama_type_settings.py -q`

Run: `node --check assets/app.js`

- [ ] **Step 6: Commit the independently testable settings feature**

```bash
git add backend/alembic/versions/2f6c8a1d4b90_add_channel_drama_type_settings.py backend/zhiju/models/settings.py backend/zhiju/models/__init__.py backend/zhiju/schemas/settings.py backend/zhiju/services/settings.py backend/zhiju/api/settings.py backend/tests/test_channel_drama_type_settings.py assets/app.js
git commit -m "feat: configure channel drama types"
```

### Task 2: Channel Hub Data Contract and Editing

**Files:**
- Create: `backend/alembic/versions/31b7d5e8a2c4_expand_channel_hub_profile.py`
- Modify: `backend/zhiju/models/identity.py`
- Modify: `backend/zhiju/models/channel_intelligence.py`
- Modify: `backend/zhiju/schemas/identity.py`
- Modify: `backend/zhiju/schemas/channel.py`
- Modify: `backend/zhiju/services/identity.py`
- Modify: `backend/zhiju/services/channel.py`
- Modify: `backend/zhiju/api/channel.py`
- Test: `backend/tests/test_channel_hub_contract.py`

**Interfaces:**
- Produces editable fields: `channels.chinese_meaning`, `channel_profiles.avatar_prompt`, `channel_profiles.banner_prompt`.
- Produces `ChannelHubUpdate` for editable channel/profile fields only.
- Produces API: `PUT /api/v3/channels/{channel_id}/hub`.
- Extends `ChannelDetailRead` with `pinned_comment_templates`, `playlists`, `branding_assets`, `drama_types`, and `relevant_skills`.

- [ ] **Step 1: Write failing schema and OpenAPI tests**

```python
def test_channel_hub_update_excludes_read_only_identity_fields():
    fields = ChannelHubUpdate.model_fields
    assert {"chinese_meaning", "default_genre", "drama_type", "description", "positioning", "avatar_prompt", "banner_prompt"}.issubset(fields)
    assert "original_name" not in fields
    assert "youtube_channel_id" not in fields
    assert "youtube_channel_url" not in fields

def test_channel_hub_update_route_is_registered():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "put" in paths["/api/v3/channels/{channel_id}/hub"]
```

- [ ] **Step 2: Run the test and verify it fails on the absent contract**

Run: `uv run pytest backend/tests/test_channel_hub_contract.py -q`

- [ ] **Step 3: Add the migration and minimal editable fields**

Add nullable `channels.chinese_meaning`, `channel_profiles.avatar_prompt`, and `channel_profiles.banner_prompt`. Do not add file paths or duplicate avatar/banner URLs.

- [ ] **Step 4: Implement the channel hub transaction**

Implement:

```python
def update_channel_hub(session: Session, channel_id: str, payload: ChannelHubUpdate) -> dict[str, object]:
    ...
```

The function locks the channel, validates an explicitly submitted drama type against an active `ChannelDramaType`, updates only editable channel/profile fields, commits once, and returns `get_channel_detail(...)`.

- [ ] **Step 5: Expand the detail aggregation using existing tables**

Return pinned comment versions, playlists ordered by `sort_order`, branding history, enabled drama types, relevant Skill current versions, recent analysis reports, and active DNA. Do not create a generic repository or serializer layer.

- [ ] **Step 6: Add transaction-level service tests**

Test that a valid update persists, a disabled/unknown drama type is rejected, and read-only identity fields cannot enter the request model.

- [ ] **Step 7: Run focused tests and migration inspection**

Run: `uv run pytest backend/tests/test_channel_hub_contract.py backend/tests/test_channel_analysis_contract.py backend/tests/test_channel_lifecycle_contract.py -q`

Run: `uv run alembic heads`

- [ ] **Step 8: Commit the channel hub backend**

```bash
git add backend/alembic/versions/31b7d5e8a2c4_expand_channel_hub_profile.py backend/zhiju/models/identity.py backend/zhiju/models/channel_intelligence.py backend/zhiju/schemas/identity.py backend/zhiju/schemas/channel.py backend/zhiju/services/identity.py backend/zhiju/services/channel.py backend/zhiju/api/channel.py backend/tests/test_channel_hub_contract.py
git commit -m "feat: add channel hub data contract"
```

### Task 3: Structured Channel Detail Workspace

**Files:**
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Test: `backend/tests/test_channel_hub_frontend_contract.py`

**Interfaces:**
- Consumes: `GET /api/v3/channels/{channel_id}`, `PUT /api/v3/channels/{channel_id}/hub`.
- Produces client state: `channelDetail`, `channelDetailTab`, `channelDetailId`.
- Produces renderer: `showChannelDetail(channelId)` and `channelDetailBody(detail, tab)`.

- [ ] **Step 1: Write a failing frontend source contract**

```python
def test_channel_detail_uses_structured_workspace():
    source = (ROOT / "assets/app.js").read_text(encoding="utf-8")
    assert "function channelDetailBody" in source
    assert 'data-channel-detail-tab="basic"' in source
    assert 'data-channel-detail-tab="operations"' in source
    assert 'data-channel-detail-tab="analysis"' in source
    assert 'data-channel-detail-tab="reference"' in source
    assert "JSON.stringify(data, null, 2)" not in source
```

- [ ] **Step 2: Run the test and verify it fails on the raw JSON drawer**

Run: `uv run pytest backend/tests/test_channel_hub_frontend_contract.py -q`

- [ ] **Step 3: Implement the structured drawer**

Use the existing drawer to avoid adding a new routing framework. Add tabs for 基础与装修、运营配置、分析中心、运营参考、版本与规则. Render missing data as “待完善”; do not render non-functional generation or external-write buttons.

- [ ] **Step 4: Add the editable basic/profile form**

Keep channel name, YouTube ID, and URL as plain read-only text. Submit only `ChannelHubUpdate` fields and refresh the detail after success.

- [ ] **Step 5: Render existing operational and analysis records**

Show pinned comments, playlists, recent reports with `initial`/`periodic` labels, current DNA, and relevant Skill versions. This task does not add CRUD for every child table.

- [ ] **Step 6: Add focused responsive CSS**

Use the existing drawer and detail classes. Add only channel-hub tab panels, compact grids, read-only identity rows, and responsive single-column rules; do not introduce another nested vertical scroll container.

- [ ] **Step 7: Run focused checks**

Run: `uv run pytest backend/tests/test_channel_hub_frontend_contract.py -q`

Run: `node --check assets/app.js`

Run: `git diff --check`

- [ ] **Step 8: Commit the structured workspace**

```bash
git add assets/app.js assets/styles.css backend/tests/test_channel_hub_frontend_contract.py
git commit -m "feat: add structured channel detail workspace"
```

### Task 4: MySQL Migration and End-to-End Verification

**Files:**
- Modify only if a real defect is found in files already touched by Tasks 1-3.

**Interfaces:**
- Consumes the completed first-phase channel hub.
- Produces acceptance evidence for code, `zhiju_dev`, API, and browser separately.

- [ ] **Step 1: Verify the target database before migration**

Run the project MySQL development helper to confirm the configured URL, `SELECT DATABASE()` equals `zhiju_dev`, current Alembic version equals the pre-migration head, and the expected channel/profile tables exist. Stop on drift; do not stamp or rebuild.

- [ ] **Step 2: Apply migrations only to `zhiju_dev` and read back**

Run: `uv run alembic upgrade head`

Read back `SELECT DATABASE()`, `alembic_version`, new columns, the drama-type rows, and channel counts.

- [ ] **Step 3: Run the full backend suite**

Run: `uv run pytest backend/tests -q`

- [ ] **Step 4: Run frontend and diff checks**

Run: `node --check assets/app.js`

Run: `git diff --check`

- [ ] **Step 5: Start an isolated development server and verify the real page**

Use a free non-production port. Verify channel list → detail drawer, all five tabs, read-only identity fields, editable profile fields, drama-type selection, report type labels, DNA and Skill-version display. Close the test server after verification.

- [ ] **Step 6: Commit only real verification fixes, if any**

If verification finds a real defect, stage only the already-scoped file that required correction and commit it with `fix: complete channel hub acceptance`. If no defect is found, do not create an empty verification commit.

- [ ] **Step 7: Report evidence layers separately**

Report feature branch and commits, tests, `zhiju_dev` migration version, API/page evidence, and explicitly state that the branch is not merged, not packaged, not deployed, and production was not changed.
