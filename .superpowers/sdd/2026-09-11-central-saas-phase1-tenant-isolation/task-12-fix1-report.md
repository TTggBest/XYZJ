# Task 12 review round 1 fix report

Status: the three Important findings are addressed in the Task 12 scope. Focused and complete tracked backend verification pass.

## Authority and boundary

- Repository: `/Volumes/TTggg_mini01_2T/ai/筱宇短剧运营-youtube/管理系统`.
- Branch: `feature/tenant-auth-system`.
- Task 12 application commit under repair: `d9cdad5376c1e2bebdd16e5c44979c7441d75ce6`.
- Read the complete Task 12 review, brief, implementation report, review package, the total-plan Task 12 section, the complete central SaaS design, and the applicable parent `AGENTS.md` before editing.
- Used strict RED/GREEN sequencing. No real database, external service, migration, push, merge, deployment, subagent, or self-review was used.
- Concurrent Task 11 files and newly appearing untracked OAuth/YouTube tests were not staged or modified by this task.

## Ruling and implementation

The Phase 1 contract is one authenticated, same-origin SSE stream per browser connection. `/api/v3/realtime/config` always advertises `/api/v3/events/stream`, and the API process that accepts a successful tenant write publishes to its own tenant-partitioned in-process broker. This preserves the central SaaS browser session contract without restoring anonymous remote publish or inventing a Phase 2 Worker protocol. MySQL remains authoritative; refresh/reconnect is the recovery path when an in-process notification is unavailable.

- `realtime_stream_url()` no longer advertises a configured remote Studio origin.
- Runtime configuration for `studio`, `worker`, and `builder` now leaves `ZHJ_REALTIME_HUB_URL` empty.
- The current README and SSE design document now state the same-origin authenticated contract and its in-process boundary.
- Removed the nonexistent `POST /api/v3/events/publish` entry from `INTERNAL_ROUTES`; the authoritative route inventory is green.
- Updated the auth non-broadcast regression to subscribe and unsubscribe with explicit tenant `tenant`.
- Full-repository call search found no remaining unscoped `RealtimeBroker.subscribe`, `RealtimeBroker.unsubscribe`, `broker.publish`, or `publish_change_event` caller.
- Removed one stale source-text assertion in `test_database_environment_switch.py`. It depended on Task 12's former hard-coded `"/api/v3/settings/runtime/environment"` middleware exclusion; the real route remains covered by the adjacent OpenAPI and API behavior tests after Task 12 switched to `TENANT_ROUTES`.

## RED evidence

Command:

`PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider backend/tests/test_realtime_contract.py::test_realtime_stream_stays_on_the_authenticated_api_origin backend/tests/test_runtime_device_contract.py::test_runtime_paths_and_sse_are_derived_from_database_role backend/tests/test_tenant_route_inventory.py::test_every_api_route_has_exactly_one_scope backend/tests/test_auth_api.py::test_auth_changes_are_not_broadcast_on_the_legacy_business_event_stream -q`

Result: **4 failed**.

- Realtime config returned `http://192.168.8.8:19732/api/v3/events/stream` instead of the same-origin path.
- Worker runtime configuration returned `http://192.168.8.8:19732` instead of an empty hub.
- Route inventory had the deleted publish route as an extra classified item.
- Auth regression raised `TypeError` because `subscribe()` omitted `tenant_id`.

The first full backend run then exposed the Task 12-caused stale source assertion in `test_database_environment_switch.py`; `401cebc..d9cdad5` shows Task 12 removed that literal while preserving the route through the authoritative inventory.

## GREEN evidence

Required focused selection plus the affected environment-switch contracts:

`PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider backend/tests/test_database_environment_switch.py::test_runtime_api_declares_builder_environment_switch backend/tests/test_database_environment_switch.py::test_frontend_exposes_switch_and_persistent_environment_state backend/tests/test_realtime_contract.py backend/tests/test_realtime_tenant_isolation.py backend/tests/test_auth_api.py backend/tests/test_tenant_route_inventory.py backend/tests/test_runtime_device_contract.py -q`

Result: **70 passed, 1 existing Starlette/httpx deprecation warning**.

## Complete backend evidence

A raw `backend/tests` rerun was temporarily blocked during collection by concurrently created, untracked `test_oauth_tenant_state.py` and `test_youtube_tenant_isolation.py`; their producer had not yet added `OAuthAuthorizationState`. They are outside Task 12 and were not changed or staged here.

Stable complete tracked backend suite:

`PYTHONDONTWRITEBYTECODE=1 git ls-files 'backend/tests/test_*.py' -z | xargs -0 uv run pytest -p no:cacheprovider -q`

Result: **1061 passed, 1 existing Starlette/httpx deprecation warning in 31.19s**.

## Verdict

Task 12 review round 1 Findings 1-3 are resolved within Phase 1's supported boundary. This report establishes code/test completion for the fix commit only; it does not claim push, merge, deployment, live-service verification, database migration, or business acceptance.
