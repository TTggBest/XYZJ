# Channel analysis Codex implementation plan

Goal: implement the approved channel-analysis proposal without running live analysis or deploying.
Architecture: independent tenant/channel analysis jobs; existing bound-host Codex channel; existing report, audience and DNA consumers.
Spec: ../specs/2026-10-29-channel-analysis-codex-integration-proposal.md

## Constraints
Preserve inherited Feishu changes and unrelated untracked files. No upstream Zhihe requests. No live model calls, merges or deployment. Cold-start is explicit; API failure cannot select it. Three documents and seven-section generation spec remain authoritative.

## Steps
- [x] Model/schema/migration and regression tests: separate analysis runs, frozen inputs, materials, claim, cancel/resume and version application.
- [x] Platform data adapter: authorized 28/90-day API sources, original Studio ZIP/CSV, screenshot inventory, channel-local metadata, explicit availability.
- [x] Codex runner: existing launcher/session, image attachments, frozen analysis skill, cached submission and local history mirror.
- [x] Analysis-center UI: materials, initial positioning, progress, preview/download, explicit apply and retry.
- [x] Targeted tests, tenant-route classification, existing executor regression and independent final review.

## Review focus
Wrong channel or tenant must not leak data. Operated channels with missing data cannot become cold-start. Failed data sets remain unavailable. Repeated uploads/submissions must not duplicate reports. Apply preserves fixed assets and historical production snapshots.

## Execution ledger
- Existing feature checkout verified; inherited tracked Feishu changes and untracked V15 work preserved.
- Ruling: user approved the concrete proposal and said start; execute inline without another planning approval.
- Validation: 40 targeted tests passed, JavaScript syntax and diff whitespace checks passed. New-table migration upgrade/downgrade tested in isolated SQLite; one Alembic head. Locked PyYAML dependency added for actual YAML validation.
- Independent review: seven concrete findings repaired; failure-response replay repair separately reviewed and tested. Old applied versions are superseded; separate task-type wakeups retained; native ZIP/actual periods and full outputs validated; collection checkpoints preserved; initial rules separated.
- Ruling: large JSON snapshots are loaded after selecting ordered IDs, avoiding the previously observed MySQL JSON sort-buffer failure without changing server settings.
- Delivery boundary: code and simulated end-to-end tests only. No merge, deployment, live migration, launcher installation, real Google extraction, model call, or authenticated visual acceptance performed. Cloud and launcher must both be updated through the existing release process before runtime acceptance.
