# Analysis Rules

## Source precedence and scope

Use sources according to the metric they can actually support:

1. Studio export total row: exact all-content 28-day totals, returning viewers, revenue, impressions, and CTR.
2. Content > Videos screenshot: rounded video-only totals and Studio-only video cards. Keep this scope separate from all-content totals.
3. Analytics API: exact daily trends, per-video performance, country, traffic source, and device splits.
4. Audience screenshot: Studio-only audience segments, gender/age, subscriptions, online time, and adjacent audience interests.
5. A/B screenshots: tested variants and Studio's watch-time-share result.
6. Local drama metadata: Chinese drama identity, plot, relationships, and content DNA.

Do not merge values with different scopes into one unlabeled metric. If the all-content total and video-only screenshot differ, explain the scope difference instead of calling it a conflict.

## Date and cohort rules

- Derive the Studio window from the CSV contents when the ZIP filename differs.
- Exclude a partial current day from API trends.
- Compare like with like: same duration class, maturity, content type, and comparable traffic conditions.
- Treat a long-form video as mature for performance comparison only after at least 7 complete days unless the report explicitly labels it early performance.
- Do not sum per-video returning viewers: viewers can overlap across videos.
- Do not let one breakout video overwrite the long-term channel identity. Promote a short-term observation to stable knowledge only after repeated-period evidence.

## Derived metrics

Calculate only when inputs are numeric and scopes match:

```text
average_view_duration_minutes = watch_hours * 60 / views
average_percentage_viewed = average_view_duration_seconds / video_duration_seconds * 100
subscriber_gain_per_1000_views = subscribers_gained / views * 1000
RPM = revenue / views * 1000
top_n_view_share = sum(top_n_views) / total_views
browse_suggested_share = browse_share + suggested_share
```

CTR summaries must be impression-weighted, not a simple mean across videos.

## Required analysis domains

Analyze:

- channel stage and 28-day / 90-day trend;
- audience geography, age, gender, device, subscription, and new/returning behavior;
- traffic model and discovery dependence;
- top, middle, and weak content cohorts;
- content DNA: relationships, conflicts, identity, family/children, CEO/revenge, and endings when supported by the dramas;
- packaging and CTR;
- watch time, APV, early retention, and long-tail/first-day behavior;
- traffic and view concentration risk;
- completed A/B tests;
- community-post performance;
- current opportunities, risks, and evidence gaps.

## CTR diagnosis

CTR is never interpreted alone. For each important cohort, jointly inspect:

- impressions and traffic source;
- CTR;
- average view duration/APV;
- video age and sample size.

Use the practical four-quadrant interpretation:

- high CTR + strong retention: packaging and content both work;
- high CTR + weak retention: packaging promise may exceed content delivery;
- low CTR + strong retention: content works but packaging/distribution needs work;
- low CTR + weak retention: content and packaging both require caution.

Do not call a tiny-impression video a proven high-CTR pattern.

## A/B-test semantics

Studio's A/B percentages are watch-time shares, not variant CTR. Record them exactly as shown and preserve Studio's Winner/Preferred/None decision. Do not convert watch-time share into CTR or claim causality beyond the test result.

## Evidence discipline

- Tie major conclusions to a metric, cohort, screenshot card, or mapped drama set.
- Distinguish fact, calculation, interpretation, and recommendation.
- Use `unavailable` rather than inventing a number or audience trait.
- Do not invent competitor behavior, algorithm penalties, user motives, or title/cover causality that the sources cannot support.

## Confidence

Set descriptive confidence:

- `high`: multiple independent sources or repeated mature cohorts agree;
- `medium`: one strong source or several partially aligned signals;
- `low`: limited samples, early videos, missing audience cards, or a conclusion dominated by one hit.
