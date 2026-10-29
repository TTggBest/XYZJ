# Output Contract

## Root documents

Write these three live files directly in the channel directory:

```text
频道用户画像与长期经营档案.md
频道当前运营诊断与运营包指导.md
<频道名>_生成规范.md
```

Their responsibilities are:

| File | Sole responsibility |
|---|---|
| `频道用户画像与长期经营档案.md` | Stable long-term channel knowledge |
| `频道当前运营诊断与运营包指导.md` | Current-period analysis decisions and its machine-readable diagnostic summary |
| `<频道名>_生成规范.md` | The sole downstream channel execution file; channel-specific expression rules derived from the two analysis documents |

Do not write these live files into `output/` or inside the history batch.

`<频道名>_频道分析报告.md` is not a required live output and must not be used as downstream operations-package input. If an older copy exists, preserve it as history; do not refresh it as part of V2.

## History structure

For each analysis run, use:

```text
<频道目录>/分析数据/YYYY-MM-DD_频道分析V2/
├── API原始数据/
├── Studio导出数据/
├── 截图/
│   └── A_B测试/
├── 分析产物原始版本/
│   └── 频道Analytics原始快照.json
├── 更新前文件/
└── 最终文件快照/
```

Store inputs and historical snapshots here. The three live documents remain at channel root.

## Normalized JSON

At minimum include:

```text
schema_version
snapshot_status
generated_at
channel
data_windows
availability_rules
channel_totals_28d
trend
audience_28d
traffic_28d_video_pct
retention_intro_30s_pct
top_videos_28d
low_videos_28d
concentration_28d
community_posts
ab_testing
source_manifest
unmatched_video_ids
```

Every Studio-only field must retain its source and scope. Every missing field must use an explicit availability state.

## Document structure

### Long-term profile

Keep these ten sections:

1. Channel basics
2. Overall performance
3. Audience profile
4. Traffic profile
5. Content profile
6. Packaging profile
7. Consumption profile
8. Stable audience preferences
9. Current channel positioning
10. Long-term strategy

Short-term anomalies must not silently replace stable conclusions.

### Current diagnosis

Keep these seven sections:

1. Current-stage diagnosis
2. What the current audience rewards
3. Current content priority
4. Current title guidance
5. Current cover guidance
6. Current description/community/hashtag guidance
7. Current decision summary

Section 7 must contain valid YAML with this authoritative structure:

```yaml
channel_strategy:
  channel_id: ""
  updated_at: ""
  data_window:
    recent_28d: ""
    recent_90d: ""
  strategy_confidence: ""
  channel_stage: ""
  audience_core: ""
  traffic_type: ""
  content_priority: []
  content_secondary: []
  content_explore: []
  content_avoid: []
  title_priority: []
  title_reduce: []
  cover_priority: []
  cover_reduce: []
  description_focus: []
  community_focus: []
  hashtag_focus: []
  scheduling_notes: []
```

The YAML is authoritative only inside the analysis layer and must agree with the human-readable body. Downstream operations-package production must not read this file; it reads only `<频道名>_生成规范.md`.

### Generation specification

Write the exact seven-section structure defined in `generation-spec-contract.md`. Convert supported channel findings into channel-specific expression guidance for titles, covers, descriptions, hashtags, community posts, and playlist routing. Do not select the current drama, invent current-drama facts, or turn short-term performance into channel identity.

## Final validation

Before completion verify:

- all three root files exist and have the correct channel name/ID;
- normalized JSON parses;
- the strategy YAML parses and matches the prose;
- date windows and all-content/video-only scopes are labeled;
- unavailable values are not encoded as zero;
- no per-video returning-viewer sum appears;
- A/B percentages are labeled watch-time shares;
- previous root files and final snapshots were archived;
- no required live file was written to `output/`.
- `<频道名>_生成规范.md` passes `scripts/validate_generation_spec.py`.
