# SDD ledger — plan: docs/superpowers/plans/2026-09-11-central-saas-phase1-tenant-isolation.md

Baseline: feature/tenant-auth-system @ 0481d3f; `uv run pytest -q` => 567 passed, 1 third-party deprecation warning.
Workspace ruling: execute in the user-requested independent feature branch already checked out; do not create a second branch/worktree. Cost if wrong: less filesystem isolation, but dev and production branches remain untouched and every task is committed separately.

## Preflight task self-consistency scan

| Task | Producer / consumer check | Result |
|---|---|---|
| 1 | route inventory and read-only preflight create their own tests | consistent |
| 2 | TenantSession/repository interfaces precede every business conversion | consistent |
| 3 | fixed default tenant and nullable roots precede child graph migrations | consistent |
| 4 | channel graph migration and channel/identity access change together | consistent |
| 5 | drama/schedule graph follows channel ownership | consistent |
| 6 | production/package graph follows channel and drama ownership | consistent |
| 7 | media/image children follow root media/workspace ownership | consistent |
| 8 | OAuth/YouTube state is DB-backed and follows account/channel roots | consistent |
| 9 | integration/sync/demo follows channel, drama, production roots | consistent |
| 10 | history/settings/audit consume completed graph ownership | consistent |
| 11 | UI consumes existing platform account/device APIs | consistent |
| 12 | SSE consumes principal cached by Task 2 | consistent |
| 13 | unique/composite constraints run after all nullable graph migrations | consistent |
| 14 | NOT NULL runs after service writes and relational constraints | consistent; platform audit rows are documented exception |
| 15 | global auth enforcement deliberately runs last | consistent |
| 16 | MySQL rehearsal consumes complete migration chain | consistent |
| 17 | browser acceptance consumes auth/UI and all isolated APIs | consistent |
| 18 | full review consumes all earlier commits and evidence | consistent |

## Shared file and interface scan

| Tasks | Shared output / input | Finding |
|---|---|---|
| 1,15 | `tenant_scope.py` inventory then auth enforcement | ordered, compatible |
| 3,4 | identity/channel/operations/settings/youtube model roots then channel children | ordered, compatible |
| 3,5 | operations model roots then drama/schedule children | ordered, compatible |
| 3,6 | production roots then production children | ordered, compatible |
| 3,7 | channel-intelligence/settings roots then media/image children | ordered, compatible |
| 3,8 | integration/youtube roots then OAuth/YouTube children | ordered, compatible |
| 3,9 | demo/integration/production roots then sync/demo children | ordered, compatible |
| 3,10 | audit root then audit query isolation | ordered, compatible |
| 3,13 | owned models then relational constraints | ordered, compatible |
| 3,14 | nullable owned models then NOT NULL | ordered, compatible |
| 4,5 | channel schedule model then drama/schedule services | Task 4 owns channel-linked columns; Task 5 consumes them |
| 4,7 | channel/media/settings models then image isolation | ordered, compatible |
| 4,8 | channel YouTube metrics model then YouTube graph | ordered, compatible |
| 4,13 | channel models then composite constraints | ordered, compatible |
| 4,14 | channel models then NOT NULL | ordered, compatible |
| 4,15 | channel/identity APIs then final auth dependency audit | ordered, compatible |
| 5,13 | operations models then composite constraints | ordered, compatible |
| 5,14 | operations models then NOT NULL | ordered, compatible |
| 5,15 | drama/operations APIs then final auth dependency audit | ordered, compatible |
| 6,9 | production model then Feishu sync tenant propagation | ordered, compatible |
| 6,13 | production model then composite constraints | ordered, compatible |
| 6,14 | production model then NOT NULL | ordered, compatible |
| 6,15 | production API then final auth dependency audit | ordered, compatible |
| 7,13 | media/image models then composite constraints | ordered, compatible |
| 7,14 | media/image models then NOT NULL | ordered, compatible |
| 7,15 | image API then final auth dependency audit | ordered, compatible |
| 8,9 | integration model OAuth ownership then integration service isolation | ordered, compatible |
| 8,13 | integration/youtube models then composite constraints | ordered, compatible |
| 8,14 | integration/youtube models then NOT NULL | ordered, compatible |
| 8,15 | YouTube APIs then final auth dependency audit | ordered, compatible |
| 9,13 | sync/demo models then composite constraints | ordered, compatible |
| 9,14 | sync/demo models then NOT NULL | ordered, compatible |
| 9,15 | sync/integration/demo APIs then final auth dependency audit | ordered, compatible |
| 10,13 | audit model then composite constraints | ordered, compatible |
| 10,14 | audit model then NOT NULL | ordered with platform-event exception |
| 10,15 | history/settings APIs then final auth dependency audit | ordered, compatible |
| 11,17 | frontend auth contract then browser tenant switching coverage | ordered, compatible |
| 12,15 | realtime API/app middleware then final auth enforcement | ordered, compatible |
| 13,14 | composite constraints then NOT NULL | ordered, compatible |

Ruling: the plan uses broad per-graph tasks that are too large for parallel writers. Implement one task at a time with read-only reviewers; parallelism is reserved for independent analysis/review so shared models and migrations cannot overwrite each other. Cost if wrong: lower raw concurrency but deterministic migration history and reviewable commits.

Task 1: fix round 1/5 (4 addressed, 0 open — corrected tenant/platform route semantics, global table exclusions, and semantic route tests; commits cec1eb7..fb0512c)
Task 1: complete (commits 0481d3f..fb0512c, review clean)
Task 2: Ruling: put `TenantSession`/`open_tenant_session` in `database.py`, `get_tenant_db` in `auth_context.py`, and entity guards in `tenant_repository.py` to avoid a database/auth circular import. SQLite is only the pure ORM test fixture; MySQL acceptance remains Task 16. Cost if wrong: these public interfaces may later need a small import-path refactor.
Task 2: complete (commits fb0512c..2dee034, review clean)
Task 3: Ruling: seed the existing-business tenant as active with lease `2099-12-31 23:59:59 UTC`; this preserves current operations and is not a billing-policy promise. Allow only a Chinese column comment addition to `TenantOwnedMixin.tenant_id`. Cost if wrong: the lease date may need a later audited admin update.
Task 3: Ruling: seed the 16 permission codes from the approved auth/device spec; super_admin gets all, owner gets all 13 tenant permissions, admin omits tenant.manage/channel.delete/platform permissions, operator gets operational writes, viewer gets four read permissions. Permission IDs equal codes and role-pair IDs use short role prefixes. Cost if wrong: a later role-policy migration must adjust mappings, but codes and business ownership remain stable.
Task 3: Ruling: after a verified non-empty backup, apply only revision `b1d4e7f2a610` to the exact `zhiju_dev` database so model and development schema stay testable between migration tasks. Cost if wrong: development data may require restoring the recorded dump; production remains untouched.
Task 3: complete (commits 2dee034..a45231a, review clean; zhiju_dev backed up and migrated to b1d4e7f2a610)
Task 4: Ruling: include only channel-owned playlist/publish/community/schedule-entry paths from `api/operations.py` and `services/operations.py`; Task 5 owns drama/candidate/change-history paths. Do not invent an unused batch archive API; current single-channel archive uses `require_tenant_entity`. Preserve global uniqueness of remote YouTube channel IDs. Cost if wrong: Task 5 may need to adjust an operations boundary, but no unused API or uniqueness relaxation is introduced.
Task 4: fix round 1/5 (2 addressed, 0 open — candidate routes now carry tenant session and media channel filters return cross-tenant 404; commits fb846e9..92605f9)
Task 4: complete (commits a45231a..92605f9, review clean; zhiju_dev backed up and migrated to c2e5f8a3b721)
Task 4: Ruling: include only channel-owned playlist/publish/community/schedule-entry paths from `api/operations.py` and `services/operations.py`; Task 5 owns drama/candidate/change-history paths. Do not invent an unused batch archive API; current single-channel archive must use the tenant entity guard. Preserve globally unique YouTube channel IDs and use same-name/different-ID fixtures. Cost if wrong: a future real bulk-delete feature will need its own all-or-nothing endpoint and tests.
Task 5: Ruling: keep `languages` and `publish_cadence_template_slots` platform-shared; authenticated users may read them, while writes require platform-admin authority. Reorder drama route registration so the static `/dramas/match` route is resolved before `/dramas/{drama_id}`. Cost if wrong: platform directory editing may need a later delegated permission, but tenant business data remains isolated.
Task 5: Ruling: retain nullable `tenant_id` during staged graph migrations; composite ownership constraints, tenant-aware unique keys, and final `NOT NULL` enforcement remain Tasks 13 and 14. Cost if wrong: the development schema temporarily relies on service/session guards until those planned database constraints land.
Task 5: complete (commits 92605f9..1fbfe71, independent review clean; focused 186 passed, full backend 827 passed; zhiju_dev backed up and migrated to d3f6a9b4c832 with 4,803 rows, 0 null tenant IDs, and 0 parent-chain conflicts)
Task 6: Ruling: preserve the existing internal start/finish/retry node protocol and recover tenant context exclusively from the persisted `production_node_runs.tenant_id`; do not invent heartbeat or the Phase 2 general Worker protocol in this task. Cost if wrong: the internal endpoints will be replaced later, but the current production graph remains isolated now.
Task 6: Ruling: validate polymorphic event entities and output-copy sources against an explicit supported-type-to-parent mapping; optional production parents may be absent but every present parent must agree. Cost if wrong: adding a future event/copy type requires extending the explicit mapping and tests.
Task 6: complete (commits 1fbfe71..401cebc, independent review clean; focused 191 passed, full backend 997 passed; zhiju_dev backed up and migrated to e4a7b0c5d943 with 9,079 rows across 16 child tables, 0 null tenant IDs, and 0 parent-chain conflicts)
Task 7: Ruling: include the actual media entry points in `services/channel.py` and the existing package artifact writer in `services/package_outputs.py`, because both create or expose file metadata governed by the new tenant prefix invariant. Do not expand into Phase 3 object storage or retention. Cost if wrong: another existing file-metadata writer would need the same narrow prefix guard later.
Task 7: Ruling: all new file metadata uses `tenants/<tenant_id>/...`; only the fixed default tenant may read pre-migration local paths through the single legacy adapter. Cost if wrong: legacy default-tenant assets may require explicit re-keying before that adapter can be removed.
Task 7: complete (commit 979df3d, independent review clean; focused 87 passed; zhiju_dev backed up and migrated to f5b8c1d6e054 with 3 runs, 1,290 items, 215 media rows, 1 workspace setting, 0 null tenant IDs, 0 parent conflicts, and 0 duplicate settings)
Task 11: review round 1/5 (1 Important open — account center displays binding status while device settings displays device status for the same device ID)
Task 12: review round 1/5 (3 Important open — remote-hub subscription disconnected from in-process publish, stale publish route inventory, and stale no-tenant broker test callers)
Task 12: fix round 1/5 (3 Important addressed, 0 open — runtime/browser publishing and subscription now share the authenticated same-origin process contract, deleted publish route removed from inventory, and all broker callers pass explicit tenant IDs; commit 4ceae07)
Task 12: complete (commits d9cdad5 + 4ceae07, independent rereview clean; targeted 70 passed and tracked full backend 1,061 passed before later parallel Task 8 edits)
Task 11: fix round 1/5 (original status-source finding addressed in commit 8cf1899; rereview found 1 new Important in the separate `assets/account-center.js` consumer, so Task 11 remains open)
Task 11: fix round 2/5 (1 Important addressed, 0 open — `assets/account-center.js` and its fixtures now consume `device_status`, `binding_status`, and the readable device/user/login fields; commit 107c8eb)
Task 11: complete (commits 995a45a + 8cf1899 + 107c8eb, independent rereview clean; Task 11 targeted 177 passed)
Task 8: review round 1/5 (1 Critical and 1 Important open — video status history used a bare session and OAuth platform configuration lacked platform-admin authorization)
Task 8: fix round 1/5 (2 addressed, 0 open — authenticated tenant video-history guard and platform-admin OAuth configuration/import authorization; commit af21985; full backend 1,075 passed before rereview)
Task 8: complete (commits 015fade + af21985, independent rereview clean; OAuth/YouTube permission matrix 116 passed; zhiju_dev backed up and migrated to a6c9d2e7f165 with 13 target tables at 0 null tenant IDs and preserved global remote channel/video uniqueness)
Task 9: review round 1/5 (1 Critical open — demo imports used globally fixed synthetic channel/video identifiers, so the second tenant hit a global uniqueness error)
Task 9: fix round 1/5 (1 Critical addressed, 0 open — tenant-scoped synthetic demo identifiers while preserving real YouTube global uniqueness; commit 8377a30)
Task 9: complete (commits f9ebff5 + 8377a30, independent rereview clean; targeted 59 passed; zhiju_dev backed up and migrated to b7d0e3f8a276 with 0 null tenant IDs and 0 strong-parent mismatches)
Task 10: review round 1/5 (1 Important open — foreign or missing tenant timeline entity IDs returned `200 []` instead of indistinguishable 404)
Task 10: fix round 1/5 (1 Important addressed, 0 open — all 29 supported business timeline types validate the parent tenant entity before event lookup; commit 13d6d6e)
Task 10: complete (commits 1967ffa + 13d6d6e, independent rereview clean; targeted 71 passed plus 4 permission checks; full backend 1,099 passed)
Task 11: fix round 2/5 (1 Important addressed, 0 open — `assets/account-center.js` now consumes `device_status`/`binding_status` and revoked bindings expose no revoke action; commit 107c8eb)
Task 11: complete (commits 995a45a + 8cf1899 + 107c8eb, independent rereview clean; targeted 177 passed)
Task 8: review round 1/5 (1 Critical and 1 Important open — video status history still uses an unauthenticated unscoped session, and OAuth platform configuration endpoints lack platform-admin authorization)
Task 13: Ruling: replace every tenant-business single-column parent reference with an explicit `(tenant_id, parent_id) -> (tenant_id, id)` foreign key and dedicated composite index, while global identity/catalog references remain single-column. Convert prior business `SET NULL` delete rules to `RESTRICT` because MySQL would otherwise null the composite key's `tenant_id`; downgrade restores the original single-column rules. Cost if wrong: a later approved migration must revise the affected delete semantics, but cross-tenant parent links remain database-invalid.
Task 13: complete (this implementation commit; focused 42 passed, full backend 1,127 passed; zhiju_dev backed up and migrated through c8e1f4a9b387 to d9f2a5b0c498 with 24 parent candidate keys, 121/121 composite foreign keys and 121/121 dedicated indexes verified through information_schema; zhiju_prod untouched)
