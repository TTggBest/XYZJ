# Generation Specification Contract

`<频道名>_生成规范.md` is the sole channel-level file consumed by downstream operations-package production. It controls how channel-appropriate packaging is expressed; it does not decide what the current drama is about.

Use `assets/generation-spec-template.md` as the output skeleton. The seven H2 markers below are a parser contract. Each must appear exactly once, in this exact order, with no other H2 sections:

```text
## [GLOBAL]
## [TITLE]
## [COVER]
## [DESCRIPTION]
## [HASHTAG]
## [COMMUNITY]
## [PLAYLIST]
```

## GLOBAL contract

`[GLOBAL]` is always first and contains exactly these fields, one per bullet, in this order:

```text
- 正式频道名：
- 目标语言：
- 目标市场：
- 频道性别方向：
- 稳定频道类型：
- 公开内容语言：
- 允许的跨语言表达：
- 频道公共语气：
- GLOBAL权限声明：
```

Use the registered canonical channel name, language, and market. Use only verified stable channel identity for the remaining descriptive fields. Write `无` when no cross-language expression is approved; do not infer permission from isolated historical examples.

The permission statement must be copied exactly:

```text
GLOBAL只确认频道身份、目标语言、目标市场和公共表达环境。GLOBAL不得替代当前剧情决定人物、事件、身份、冲突、爆点、结果或视觉场景；当前剧目的具体包装内容只能来自当前剧情事实、对应模块Core及已验收的单剧动态输入。
```

GLOBAL may affect only:

- channel identity;
- target/public language;
- target market;
- approved cross-language boundaries;
- abstract public tone.

GLOBAL must not contain:

- views, watch time, CTR, impressions, retention, subscriber changes, rankings, percentages, date windows, channel stage, or current strategy;
- recent winning/weak topics or current content priorities;
- specific plot materials or visual scenes such as DNA tests, twins, CEO, heirs, boardrooms, weddings, revenge, recognition scenes, or current-drama selling points;
- title directions, title/cover examples, mappings, fixed hooks, or module instructions.

`频道性别方向` and `稳定频道类型` are identity descriptions only. They must not be treated as permission to invent characters, relationships, events, or scenes for a current drama.

## Module boundaries

- `[TITLE]`: channel-specific title expression, language, tone, structure, and prohibited/reduced phrasing. It must not invent plot facts.
- `[COVER]`: channel-specific visual communication rules. People, props, relationships, events, and scenes must come from current-drama evidence or its accepted module Core.
- `[DESCRIPTION]`: channel-specific public-language, tone, structure, and disclosure boundaries for descriptions.
- `[HASHTAG]`: channel-specific hashtag language/ecosystem and formatting rules. Current-drama topic tags require current-drama evidence.
- `[COMMUNITY]`: channel-specific interaction tone, question style, and public-language rules. Do not preselect a plot angle.
- `[PLAYLIST]`: channel-specific naming, language, and routing expression. The actual playlist choice follows the current drama and accepted workflow input.

Rules for one module must live only in that module's section. Do not add shared strategy sections, current content-selection sections, examples that hard-code a plot, or another machine-readable strategy block.

## Source boundary

Build GLOBAL from registered identity plus verified stable profile conclusions. Build module rules from the long-term profile and current diagnosis, retaining only expression rules supported by evidence. Current metrics and short-term observations may justify a module rule during analysis, but the generated rule must not embed those metrics or turn a recent drama topic into a permanent instruction.

Before completion run:

```bash
python3 scripts/validate_generation_spec.py \
  "<频道目录>/<频道名>_生成规范.md" \
  --expected-channel-name "<注册表正式频道名>" \
  --expected-language "<注册表目标语言>" \
  --expected-market "<注册表目标市场>"
```
