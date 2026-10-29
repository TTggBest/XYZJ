# Input Asset Contract

V2 has exactly three primary source groups. The user supplies groups B and C; Codex obtains group A.

The user may place B and C together in one temporary handoff folder using this structure:

```text
频道分析输入/
├── 内容 YYYY-MM-DD_YYYY-MM-DD 频道名.zip
├── 内容_视频_28天.png
├── 观众_28天.png
├── 帖子_28天.png
└── A_B测试/
    ├── <video_id_1>.png
    └── <video_id_2>.png
```

The handoff folder name is not authoritative. Resolve the channel through the registry and verify the visible channel identity/source contents before filing the assets into history.

## A. API data pulled by Codex

### YouTube Data API

Collect when available:

- channel ID, title, creation date, public view/video/subscriber totals;
- video ID, title, description, publish time, duration, privacy/status, thumbnail URL;
- public views, likes, comments, and made-for-kids state.

### YouTube Analytics API

Collect when available:

- daily views, watch time, average view duration, average percentage viewed, subscribers gained, likes, comments, and shares;
- per-video views, watch time, average view duration, average percentage viewed, and subscribers gained;
- country/region distribution;
- traffic-source distribution;
- device-type distribution.

The API window ends on the latest completed day, not an incomplete current day.

## B. One Studio table-export ZIP supplied by the user

Required: one native YouTube Studio `内容` export covering the recent 28 days. It normally contains:

```text
表格数据.csv
图表数据.csv
总计.csv
```

Keep the original ZIP. Read the actual CSV dates rather than trusting only the ZIP filename. The ZIP may contain videos and community posts; classify rows by content type.

Expected fields include, when Studio provides them:

- content/video ID and title;
- publish date and duration;
- returning viewers;
- views and watch hours;
- subscribers and revenue;
- impressions and impressions click-through rate.

Only one recent 28-day ZIP is required. Do not require a separate 7-day ZIP: V2 derives recent comparisons from API daily data.

## C. Studio screenshots supplied by the user

Capture full-page screenshots at the recent 28-day window unless the card itself uses a fixed different window.

### Required screenshot 1: Analytics > Content > Videos

Capture the full page containing:

- video-only views, impressions, CTR, and average view duration;
- intro retention / 30-second top and bottom videos;
- traffic-source percentages;
- top videos.

### Required screenshot 2: Analytics > Audience

Capture the full page containing every available card:

- monthly audience;
- new, casual, regular, or returning audience cards;
- subscriber status and bell notifications;
- gender and age;
- device type and top geographies;
- subtitle language;
- viewer online-time heatmap;
- channels and content the audience also watches.

Cards that Studio suppresses because of insufficient data are recorded as `unavailable`; they are not treated as missing screenshots.

### Required screenshot 3: Analytics > Content > Posts

Capture the full page containing:

- post impressions;
- likes;
- subscribers gained;
- top posts.

If the channel has never used posts, record this area as `not_applicable`.

### Required screenshot group 4: Completed title/thumbnail A/B tests

Capture each completed test that is visible and relevant to the analysis window. Each screenshot must show:

- video identity;
- test dates/status;
- every tested title and thumbnail;
- watch-time share for each variant;
- Winner, Preferred, or None result.

Suggested filenames:

```text
内容_视频_28天.png
观众_28天.png
帖子_28天.png
A_B测试/<video_id>.png
```

Classify screenshots by visible page content, not filename alone.

## Internal supporting evidence

These are read by Codex and are not extra assets the user must package:

- `运营/工作流运营/公用/频道注册表.json` for channel identity and operating context;
- the channel's `剧目/` directory for video-to-drama mapping, plot, relationships, and existing creative context;
- existing root reports only as prior conclusions to audit, never as a substitute for current data.

## Availability states

Use only:

- numeric value: a trustworthy measured value exists;
- `unavailable`: the metric should exist, but the source/API did not provide enough trustworthy data;
- `not_applicable`: the metric does not apply to this channel/object;
- `pending`: the asset or calculation is expected but not completed yet.

Never encode missing data as numeric zero.

## Explicitly removed asset

YouTube Reporting Reach is not part of V2. Do not create, wait for, or download a Reporting Reach job. Impressions and CTR come from the Studio export and visible Studio pages.
