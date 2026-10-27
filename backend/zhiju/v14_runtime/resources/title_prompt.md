---
name: xy-title
description: Generate title sets for the current Xiaoyu short-drama package. Use this after the plot summary is available. For each search-result group, create 3 first-person titles that fit the channel format and stay within 100 visible characters.
---

# XY Title

## Purpose

This step only does one thing:

- generate title sets for the current drama package

Goal of this skill:

- make title generation default to short, hard, direct, click-driven wording
- avoid soft, roundabout, abstract, over-explained, or literary titles
- use a declarative double-explosion structure: A makes the viewer angry or shocked; B makes the viewer angrier, more shocked, or more satisfied
- make A establish immediate emotional debt through a concrete event, then make B directly repay it through a perceptible position change

It does not search plot, does not decide covers, and does not do community or description work.
Workflow position:

- run this after `xy-find`
- run `xy-cover` only after title review is approved
- run `xy-place` only when the user asks for description
- run `xy-post` only when the user asks for community
- do not run `xy-merge` before `xy-cover`, `xy-place`, and `xy-post` are all finished

## Inputs

Read:

01_频道数据.md
01_搜索资料.md
01_市场包装证据.json 中经过控制器裁剪的 final_angles

The controller may also provide `creative_history`, containing already accepted packages for the same drama in other channels. It is negative-reference material only.

## Steps

1. Before generating anything, check whether `01_频道数据.md` exists in the current package folder. If it does not exist, invoke `xy-data` first and create it.
2. Read all four authoritative plot fields behind `01_搜索资料.md`: `内容概述`, `剧情档案`, `剧情套路`, and `核心人设`. Do not reduce them to the short summary before title work.
3. Read only the controller-supplied `market_packaging.final_angles`. Use A, B, and C as the three packaging directions in that order. Do not rescan raw market videos or infer that a story-derived fallback has market validation.
4. Read `01_频道数据.md` and get the current channel's title format.
5. Realize each angle as one target-language title while keeping the angle's factual conflict/payoff core and obeying the title rules. Recommendation scoring may reorder the accepted outputs afterward.

## Rules

- Read `01_频道数据.md` and get the current channel's title format.
- Output one title set per search-result group from `01_搜索资料.md`.
- Do not force exactly 1 title set.
- If there is 1 search-result group, output 1 title set.
- If there are 2 search-result groups, output 2 title sets.
- If there are 3 search-result groups, output 3 title sets.
- Each title set must contain exactly 3 titles.
- Before controller recommendation sorting, direction 1 must implement final angle A, direction 2 final angle B, and direction 3 final angle C. Market evidence chooses the packaging proposition; this stage chooses the target-language expression. Do not replace the supplied directions with an independent scan of the plot or market videos.
- The 3 generated titles inside the same title set must not share the same direction, scene, or meaning.
- V14 has no fixed localized title-theme candidate library. Never copy or select
  a reusable direction slogan merely to satisfy channel fit. Build each title
  from this drama's strongest drama-specific marketing mechanism and the current channel
  direction; generic theme labels are not mandatory title text.
- For the current drama result group, the output must strictly follow the title rules.
- Generate every final title at no more than 95 Unicode code points, including emoji, brackets, spaces, and punctuation, so it stays safely within the validator's hard 100-code-point limit.
- Strictly forbidden semantic concepts in every generated title-owned field, regardless of target language, translation, inflection, or euphemistic spelling: rape; sexual assault; molestation; drugged; date rape or drugging; sold a person; human trafficking; kill; murder; shooting or killing; suicide; self-harm; corpse or dead body; bloody or gory; torture; poisoning to death; brutal killing.
- Prefer not to use these semantic concepts; freely choose another hard, clickable expression whenever possible: domestic violence; abuse; kidnapping; death threat.
- Apply this blacklist during generation before returning JSON. Do not rely on a downstream Validator or cleaning pass.
- Use controller-supplied `recent_channel_title_usage_7d` only as soft seven-day wording guidance. At or above a numeric preference, choose another equally hard expression whenever possible: 复仇/背叛 up to 2; 报复、羞辱、抛弃、赶出家门、被赶走、毁掉、摧毁、骗局、出轨、情人/小三、偷走、夺走、陷害、诬陷、赶出公司、开除、破产 up to 1; 欺骗 up to 2.
- Minimize 绝望、憎恨、恨我; avoid “毁了我的人生” when possible; rate-limit “让他付出代价” and “我要让他们后悔”. Missing history or an exceeded preference must never block, reject, or independently retry production. Preserve A+B click strength.
- Recount the actual final title string; never trust or merely copy the model's own `char_count` field.
- Titles must use genuine first-person involvement: the narrator must be directly involved in the explosive event as its participant, target, relationship party, or counterattacker. Do not enforce a fixed first-person vocabulary, starter list, exact pronoun position, or reusable sentence pattern. Use the most natural first-person grammar for the current channel language. A detached third-person story in which the narrator is not personally inside the event is invalid.
- Based on `01_频道数据.md`, determine whether the current channel is male-frequency or female-frequency, then use the matching male/female first-person perspective when writing titles.
- If a title uses a child, baby, underage daughter or son, twins, or another cute-child hook, make that child angle unmistakable.
- Use an optional amplifier only when current task evidence, channel-permitted marketing extrapolation, or the frozen contract supports it. Never invent a new identity, amount, asset, power, or relationship merely to intensify a title.
- The 3 titles inside the same title set must never feel similar.
- Put the strongest and most recommended title first inside each title set.
- Give every direction a unique integer `recommendation_score` from 1 to 100. Score A explosion strength, B escalation/payoff strength, instant clarity, emotional shock, channel fit, and downstream visual potential. When exactly one or two supplied final angles are market-backed, the controller places those market-backed directions first and sorts within each source group by score. When all three or none are market-backed, it sorts all three by score. It then rewrites indexes into the final title 1/2/3 delivery order.
- A and B must both be declarative. Never use a question, rhetorical question, `Why/What/Who/How` hook, or question mark in any channel language.
- `child_angle` is a downstream cover-execution flag, not a keyword detector. Set it to `true` only when the selected direction has a born minor who can truthfully appear, safe and supervised, in the same single continuous moment and physical location as the chosen cover event. A title may mention a child while using `child_angle=false` when its strongest visible payoff is an adult-only later consequence and the child cannot truthfully share that moment. An explicitly adult or grown daughter/son is not a child angle.
- Channel type, drama name, and child wording must never force all 3 directions to set `child_angle=true`.
- Resolve child presence independently from each supplied Find final angle. An angle whose only child fact is not yet born uses `child_angle=false` unless that same angle also contains a born minor. A deceased, absent, or earlier-life child does not require `child_angle=true` for a later adult-only consequence. When `child_angle=true`, `safe_cover_scene` must be one executable single moment in one physical location; never use a split screen, inset memory, separate memory region, collage, or temporal montage. Every such direction must provide `safe_cover_scene`, `child_role`, and `visual_thesis` before cover generation. Its cover must visibly include the relevant child or children; a toy, photo, bag, silhouette, or adult-only implication does not count.
- Keep the public A+B title explosive. In `visual_thesis`, `child_role`, and `safe_cover_scene`, never make a minor the visible target of abandonment, humiliation, hostile surveillance, coercive parenting, police restraint/control, adult confrontation, or bedroom/bedside intimacy. Move the visible wrongdoing, confrontation, or consequence onto adults; keep the required child calm, protected, supervised, and useful as a relationship, identity, reunion, or family anchor. Do not delete the child and do not weaken the title.
- Puzzle play, breakfast, blowing bubbles, building blocks, drawing, and other calm child activities are allowed whenever they express or support the title promise. They are not mandatory fallback scenes and must not replace the title's actual explosive event with unrelated peace.
- The title's only hard content gate concerns actual minors: never humiliate, insult, bully, abuse, sexualize, or assign age-inappropriate conduct to a minor. The same harsh conflict words are allowed when the affected person is an adult. `adult daughter`, `grown son`, 成年女儿, and 成年儿子 are adults.
- A child may appear in a safe hospital, clinic, ward, waiting area, rehabilitation area, or ordinary examination setting. Do not treat the setting word itself as a violation.
- Different titles inside the same title set may use related explosive points, but the wording and angle must not feel repetitive.
- The 3 directions inside the same title set must use different emotional debts and position changes, not merely different isolated nouns.
- Do not simply translate the Chinese drama name.
- Do not translate, paraphrase, or reuse any title, A/B hook pair, specificity anchor, or editorial angle from same-drama `creative_history`.
- Sharing objective plot facts is allowed; sharing the selected marketing direction is not. Choose a materially different conflict/payoff combination for this channel.
- Do not change the output format.
- The exact frozen channel title shell and every applicable child-safe staging requirement remain binding on the initial attempt and every retry. Fixing another validation error must not regress a requirement that previously passed.
- A format retry may replace only A and B inside the exact frozen shell. A cross-channel collision retry must change the actual hook pair, specificity anchor, and editorial moment rather than paraphrasing the rejected title.

## Title Rules

The title format must follow the channel-specific format defined in `01_频道数据.md`.

Every title uses one declarative A+B causal chain. A creates immediate emotional debt through a concrete, perceptible event. B directly repays that debt through a clear position change.

Generate in this exact order:

```text
strongest immediate emotion
-> concrete perceptible event
-> relationship inside that event
-> protagonist's response, choice, or gain
-> clear position change
-> optional amplifier
-> single A-to-B causal chain
```

Prioritize events that directly change the position between people. An event's type does not determine its priority; priority depends on whether it directly causes selection, exclusion, recognition, replacement, protection, or a change in status between people. A procedural fact receives high priority only when it carries such a position change.

Position change is an abstract result dimension. It may concern relationship, identity, power, interests, resources, social position, relationship commitment, or fate. These dimensions are not a candidate library, and no one dimension is mandatory.

B does not need to reproduce a literal plot event or ending, but it must directly answer A rather than start a second plot line. Any amplifier must remain grounded in current task evidence, channel-permitted marketing extrapolation, or the frozen contract.

Production-facing rules must remain abstract. Do not inject prebuilt story examples, fixed action combinations, fixed identity combinations, fixed result combinations, or fixed reversal templates. Actual plot evidence, channel context, and negative creative history remain valid dynamic inputs.

Finalize the marketing semantics, A-to-B emotional debt, and position change before wording the title. Then realize that unchanged meaning naturally in the current target language and market. The goal is to reduce first-read comprehension cost, not to make the title more literary, complete, or narrative. Keep this priority: relationship clarity, action clarity, result clarity, natural word order, then conciseness. This language realization may reorganize grammar, clause order, pronouns, punctuation, time placement, locally natural forms of address, and accepted loanwords when the current channel context supports them. It must not weaken the conflict, reversal, payoff, or position change, must not change facts or invent identities, amounts, assets, power, or relationships, and must not add explanatory background. Do not create or use a fixed sentence-pattern library for any language.

Before returning the localized title, perform a model-only native-language self-check: a local cold viewer should immediately understand who did what to whom; the wording should not preserve unnatural Chinese source order; it should sound locally natural rather than merely grammatical; it should be shortened or smoothed only when the original click strength remains intact; and the relationship, action, and result should remain immediately clear. This is generation and internal ranking guidance only, not a new Schema field, mechanical Validator, or Controller semantic detector.

Before returning candidates, perform a model-only self-check:

1. Does A create immediate emotion for a cold viewer?
2. Does A contain a concrete, perceptible event?
3. Does B directly repay the emotional debt created by A?
4. Is A-to-B understandable without the full plot background?
5. Is there only one main emotional causal line?

Use this self-check only for candidate generation, ranking, and internal rewrite. It must not become a mechanical Validator or an independent Controller semantic detector.

### Mandatory hook ledger

Before writing each final title, record these machine fields:

- `hook_a_type`: protocol-only value from `betrayal`, `humiliation`, `abandonment`, `theft`, `forced_choice`, `life_crisis`, `child_separation`, `identity_suppression`, `public_attack`, `marriage_trap`, `money_power_attack`, `shocking_discovery`
- `hook_a_fact`: the concrete emotional debt expressed in Chinese
- `hook_a_evidence`: a brief internal source note or marketing rationale for A
- `hook_b_type`: protocol-only value from `identity_reveal`, `public_slapback`, `revenge`, `power_reversal`, `villain_cost`, `family_collapse`, `regret_chase`, `child_recognition`, `marriage_reveal`, `life_or_death_payoff`, `wealth_reveal`, `alliance_victory`, `arrival_mystery`, `relationship_mystery`, `secret_object`, `public_shock`, `forced_choice_escalation`, `countdown_crisis`, `unseen_consequence`
- `hook_b_fact`: the concrete emotional repayment expressed in Chinese
- `hook_b_evidence`: a brief internal source note or marketing-amplification rationale for B
- `specificity_anchor`: the current-task detail that makes this title belong to this drama
- `public_payoff_anchor`: one short Chinese internal position-change note that directly answers A; do not treat the Chinese review translation as a verbatim proof field

Evidence fields are internal notes, not a verbatim-proof gate and not final title copy. The plot and channel materials are marketing raw material; do not turn the title into a translated synopsis.
The `translation` field is only a Chinese review aid. When supplied, make it useful to the reviewer, but its presence, punctuation, shell, wording, semantic keyword choice, and similarity to other review translations do not decide whether the target-language title is accepted or retried.
Preserve numbers and units exactly. Convert Chinese units correctly: `1亿 = 100 million = 0.1 billion`; therefore `20亿 = 2 billion`, never `20 billion`.
The three titles must use three different specificity anchors and at least two different A types and B types.

The hook type values only encode the already chosen current-task result in the unchanged output protocol. They must not be used as a creative candidate list.

Apply the cold-viewer test before finalizing every title. A viewer who has never seen the drama must understand the hook immediately. Replace bare story-internal proper nouns with a universally understandable description of the current relationship, event, or position change. Internal names may remain only in evidence fields.

Reject a B beat that remains an abstract story summary or starts a second unrelated causal line.

Final standard:

- `A` should make the viewer empathize
- `B` should make the viewer feel the promised payoff

When generating titles, do not mechanically reuse a fixed sentence shell. Generate the most clickable `A` and `B` automatically based on the plot core, channel language, target audience, and story type.

## Direction Split Rule

The 3 directions inside one title set must use materially different emotional debts and position changes. Do not obtain diversity merely by swapping isolated nouns.

A few generic outcome labels do not count as real direction differences.

## Hard Style Constraints

- Prefer short clauses, not long explanatory clauses.
- Prefer impact words, not logic-linking words.
- Do not stuff full background explanation into the title.
- If there is a harsher and more concrete expression, do not use a polite or elegant summary expression.
- Unless the plot truly has no stronger direct hook, do not use soft filler words or generic summary wording.
- Avoid titles that read like a plot synopsis sentence.
- Avoid titles that sound like emotional review copy instead of thumbnail click copy.

## Reject And Rewrite

Reject and rewrite the current title set before finalizing if any of these are true:

- the first half is not an immediately felt clickable stimulus
- the second half does not directly repay A's emotional debt through a perceptible position change
- A or B is a question, rhetorical question, generic `Why/What/Who/How` hook, or contains a question mark
- B is weaker than A, merely repeats A, or starts a second unrelated causal line
- the title humiliates, insults, bullies, abuses, sexualizes, or assigns age-inappropriate conduct to an actual minor
- the title explains background instead of showing the strongest hook
- the title hides the concrete explosive point behind vague wording
- the title sounds polite, literary, or overly explanatory
- the title could be reused on 20 other dramas by changing only one noun
- all 3 titles use the same emotional debt and position change
- the title requires reading twice to understand
- the title contains too many plot points and feels crowded

## Preferred Thinking Order

Before writing each title inside each title set, decide in this order:

1. What is the strongest immediate emotion?
2. Which concrete, perceptible event creates it?
3. Does that event directly change the position between people, regardless of event type?
4. Which relationship makes that event instantly understandable?
5. What response, choice, or gain changes the protagonist's position?
6. What is the resulting position change?
7. Is an evidence-grounded optional amplifier useful?
8. How can this become one short A-to-B causal chain distinct from the other two?

## Output File

Write the result to `04_标题方案.md`.

Output one title set per search-result group from `01_搜索资料.md`.
Do not force exactly 1 title set.
Repeat the same title-set structure dynamically according to the real result count.

Required structure:

```text
# 标题方案

搜索资料1：
source_block_label：搜索资料1
video_id：xxxx
id：xxxx
剧名：xxxx

方向1：xxxx
标题1：xxxx
翻译：xxxxx
字符数：xx

方向2：xxxx
标题2：xxxx
翻译：xxxxx
字符数：xx

方向3：xxxx
标题3：xxxx
翻译：xxxxx
字符数：xx

复制数据：
xxxx   (generated title 1)
xxxx   (generated title 2)
xxxx   (generated title 3)
```

Repeat this same title-set block as `搜索资料2`, `搜索资料3`, `搜索资料4`, and so on only when more search-result groups actually exist.

Also write structured data to:

```text
04_标题方案.json
```

Each result object in JSON must carry both:

- `result_id`: the unique per-result-group ID such as `Qe7OMYCtRQk_1`
- `video_id`: the shared source video ID such as `Qe7OMYCtRQk`

Return JSON that matches the controller-supplied response Schema exactly. The
Schema, not a story-filled example, defines every required field and nesting
level. Do not add fields outside that unchanged Schema.

## Hard Validation

Before any title output is accepted, validate the exact `标题格式` and channel rules from the current package's `01_频道数据.md` and the channel's `频道名_生成规范.md`.
Run validation for each title set separately. Do not use a separate workbook or an unavailable validator script.

Rules:

- If validation returns `FAIL`, do not output anything to the user.
- Fix the titles and rerun validation until it returns `PASS`.
- Do not restate the format from memory.
- Do not infer or normalize spaces, brackets, emoji separators, or fixed prefix text yourself.
- The current package snapshot and its channel generation specification are the only sources of truth.
- In chat replies, do not retype or explain the formula text.
- In chat replies, unless the user explicitly asks to see the raw workbook cell, only report `PASS` / `FAIL` for validation status.

Update `workflow_state.json`: set `xy-title` to `done`.
