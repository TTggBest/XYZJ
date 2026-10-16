---
name: xy-find-market
description: Search YouTube for V14 market-packaging evidence after authoritative plot truth is available.
---

# V14 Market Packaging Search

You receive authoritative plot truth and one channel selection context. Plot truth is the only authority for people, relationships, events, identities, outcomes, and chronology.

Use web search to investigate YouTube packaging for the exact drama or demonstrably same-source content. Search with the Chinese drama title, then refine with verified character, relationship, and plot terms when necessary.

Use the supplied date boundaries in this order:

1. Search the recent 180-day window first.
2. If it does not yield enough distinct verified angles, extend to 365 days.
3. If still insufficient, inspect relevant older results.
4. Fill every remaining final direction from plot truth without claiming market verification.

Prefer videos with high visible views and, when the surrounding channel data makes it observable, clear performance above that channel's ordinary recent level. Absolute views and relative performance are market signals, not proof that one title element caused the result.

Record only real YouTube watch URLs and metadata actually obtained during search. Do not fabricate or infer missing URLs, dates, view counts, channel names, or titles. Omit a video when its required publication date cannot be verified. A missing visible view count may be returned as null.

For every retained video:

- state the packaging angle it sells;
- state the visible moment implied by its title or thumbnail evidence;
- compare that angle with plot truth;
- mark fact verification passed only when plot truth supports it;
- set eligibility false whenever fact verification fails.

Keep failed matches in `market_videos` only when they are useful audit evidence. They must never be referenced by a candidate or final angle.

Cluster repeated uploads that sell the same underlying conflict and payoff before counting reliable market angles. `verified_market_angle_count` is the number of fact-verified, clustered market angles, not the number of videos.

Build `angle_candidates`, then select exactly three final directions in A, B, C order. Each final direction must be supported by plot truth and materially different from the others. Use channel context only to rank which true angles best fit the channel; it may not invent or force a plot element.

Source semantics:

- `external_youtube`: a video found outside the current channel.
- `internal_channel`: a video from the current channel.
- `external_market_verified` / `internal_performance`: a clustered angle backed by eligible video references.
- `story_derived`: no market claim; references must be empty, confidence must be `story_only`, and freshness must be `none`.

Search status describes execution, not market-angle count:

- `completed`: the requested search sequence ran normally, even if no verified angle was found.
- `partial`: part of the requested search sequence or required metadata could not be completed.
- `failed`: web search could not execute; still return three story-derived final angles.

Set fallback used when fewer than three verified market angles are available and explain why. Do not output final titles, translations, channel slogans, or final cover prompts. Return only the required JSON object.
