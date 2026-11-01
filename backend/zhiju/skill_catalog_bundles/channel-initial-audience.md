---
name: channel-initial-audience
description: 为没有可用 YouTube 运营数据的新频道建立冷启动定位，并生成与 xy-yt-report-v2 同名的长期档案、当前诊断、生成规范及初始事实快照。依据频道名、中文含义和已确认题材；有实测数据的频道分析使用 xy-yt-report-v2。
---

# 新频道冷启动定位

## 调用

```text
channel-initial-audience <频道名> [中文含义、初始题材或定位、目标语言/市场]
```

频道名是唯一必需的显式参数。先从用户本次输入、`运营/工作流运营/公用/频道注册表.json`、该频道已有的 `频道初始定位.md` 和频道目录读取已确认信息；本次用户说明优先于旧资料。频道名的中文含义可以翻译，但由名称联想到的题材或受众只能写成待验证的定位假设。若目标语言、目标市场或频道目录无法唯一确定，先查现有目录；仍无法确定时再询问。频道 ID、地址等未确认项写 `unavailable`，跨语言许可未获明确批准时写 `无`，不要猜。

## 适用边界

本技能只用于无可用 Analytics/Studio 运营数据的新频道。无需先进行 YouTube OAuth 授权，也不要求 ZIP、截图或外部 YouTube 搜索。不要调用 API、把频道名当成观众行为证据，或宣称已有高表现题材、CTR 规律、真实受众及最佳发布时间。有可用数据时转用 `xy-yt-report-v2` 做正式分析；不要用冷启动文件覆盖已有实测结论。

## 产出

在 `<频道目录>/` 直接写入与 V2 同名的三份正式文件：

1. `频道用户画像与长期经营档案.md`
2. `频道当前运营诊断与运营包指导.md`
3. `<正式频道名>_生成规范.md`

读取同级技能 `../xy-yt-report-v2/references/output-contract.md` 的根文件职责与十节/七节结构，以及 `../xy-yt-report-v2/references/generation-spec-contract.md` 和 `../xy-yt-report-v2/assets/generation-spec-template.md` 的生成规范结构。只复用**输出格式**，不执行 V2 的授权、素材或实测分析流程。`<正式频道名>_生成规范.md` 仍是给后续工作流读取的唯一频道级文件。

同时在 `<频道目录>/分析数据/YYYY-MM-DD_频道冷启动/分析产物原始版本/频道Analytics原始快照.json` 保存本次初始事实与来源。该 JSON 明确写 `snapshot_status: cold_start_no_analytics`，包含 V2 契约中的 `schema_version`、`generated_at`、`channel`、`data_windows`、`availability_rules`、`source_manifest` 等字段，记录频道身份、中文含义、用户确认的题材/定位及各项来源；V2 的各分析域均保留，没有数据的域一律标 `unavailable`，不填 `0`。这份快照只含初始事实，不声称有 Analytics 数据。不创建空的 API、Studio 或截图文件夹。将三份交付文件复制到本批次 `最终文件快照/`。若根目录已有同名冷启动文件且用户要求更新，先复制到 `更新前文件/`；若已有实测版，则保留实测版并报告冲突。

## 写法

- **长期档案**：保留十节。基础信息写已确认事实；总体表现、人口、地域、设备、流量、CTR、留存等无数据项写 `unavailable`。内容、包装、消费和长期策略仅写基于频道定位的编辑假设与待验证方向，不写“观众喜欢”“高 CTR”“已经证明”。
- **当前诊断**：保留七节。状态写“冷启动/探索，尚无运营数据”，流量趋势与用户变化写 `unavailable`。内容优先级、标题、封面、Description、Community、Hashtag 写可执行的**初始假设**，都以单剧真实剧情为条件。第七节保留 V2 契约的 `channel_strategy` YAML 字段和顺序，`strategy_confidence: low`、`channel_stage: exploration`；未知数据窗口、受众和流量类型写 `unavailable`，正文与 YAML 一致。
- **生成规范**：严格保留 `[GLOBAL]`、`[TITLE]`、`[COVER]`、`[DESCRIPTION]`、`[HASHTAG]`、`[COMMUNITY]`、`[PLAYLIST]` 七段。GLOBAL 只写已确认的频道身份与语言环境；频道类型若来自用户确认，标明是冷启动设定。其他段写频道表达方式及剧情事实边界，不把题材假设写成每部剧必有的剧情，不创造固定高 CTR 词库、播放列表地址或运营时段。

先形成简短的“频道初始定位”（事实、中文含义、初始题材、差异化假设、待验证项），再把它分别落实到上述三份文件；无需额外生成第四份 `频道初始定位.md`。已有该文件时可把它当作来源，保留原件。

## 完成核对

核对三份根文件与 JSON 存在，频道名/语言/市场一致，所有缺失指标用 `unavailable` 而非 `0`，冷启动假设在正文及 YAML 中均未被写成实测结论，七段生成规范符合 V2 契约。运行：

```bash
python3 ../xy-yt-report-v2/scripts/validate_generation_spec.py \
  "<频道目录>/<正式频道名>_生成规范.md" \
  --expected-channel-name "<正式频道名>" \
  --expected-language "<目标语言>" \
  --expected-market "<目标市场>"
```

从本技能目录运行该命令，或把脚本路径改为对应绝对路径。完成时给出三份根文件和事实快照的链接，并指出哪些核心判断仍待 Analytics/Studio 验证。
