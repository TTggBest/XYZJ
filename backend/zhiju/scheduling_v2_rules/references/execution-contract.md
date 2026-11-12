# 执行契约

本包是 `channel-scheduling-v2` 修订1，不是 v1 的修订5。智矩目录、冻结快照与执行器按独立标签调用；保留 v1 的全部修订、默认选择和旧任务输入。只有用户选择默认版本后，新建任务才改用该版本；创建本包本身不切换默认、不重排旧任务。

云端与本机执行器都须包含v2序列编排实现，最低协议16。协议15仅支持此前的分析r5等能力，不代表支持本v2。

## 输入与三阶段调用

`input_snapshot` 提供 `channel`、`guidance`、`operating_reference`、`analysis_topics`、`slot_topics`、`candidates`、`history`、`slots`、`targets`、`selection_evidence`、`skill_version` 及既有模型设置。日期原值为系统所选北京时间日期，模型不计算时区。

1. **全文评估**：按系统大小分批读取全部候选四个剧情字段。按给定 schema 返回实际题材、方向编号、真实原文和现有播放列表 ID。不适配也要返回评估，供下一阶段比较，不能作为强主题补位。
2. **全库相对比较**：读取全部评估、本频道逐视频证据、来源窗口、已应用历史分析和 `previous_review`。返回主辅观看承诺、证据状态、相对层级、每部的细分匹配/市场证据状态/来源理由，以及反馈和待办。每个候选 ID 恰好出现一次；阶段1未覆盖会报错，不静默跳过。
3. **序列编排**：读取比较结果、所有候选的全文评估和原文引用、档位和历史，返回每个目标档位，包括缺口。全文已在阶段1分批读取，原剧情保留在冻结快照，不在每阶段重复堆入长文本。`predecessor_drama_id` 指按实际发布时间排序后的前一个非空本次排期；首档为 null。这只是编排关联，不是观众真实观看路径。

## 结果

`rows` 沿用现有预览字段，并提供：

- `predecessor_drama_id`：前一非空档；
- `alternative_drama_id`、`comparison_reason`：本档尚可用的最接近替代项与取舍；只有没有其他同方向强匹配可用时替代项才为 null；
- `pairing_reason`：具体同日/前后承接假设；
- `packaging_promise`、`opening_check`：真实看点与待核验开场问题，不是已制作或已审阅声明；
- 系统加入 `selection_focus`、`media_verification=unverified`、真实题材/匹配等级、时区时间和警告。

`planning_review` 保存全部候选判断、观看承诺及证据状态、表现/反馈/包装分析、`next_actions`、证据采集时间和缺失项。云端会再次校验完整覆盖、原文、强匹配、替代项和序列关系；结果错误重试编排，无法通过则报错，不回退为按时长选片。

采集层当前只读既有 Analytics 窗口与已应用 Studio 资料；若缺展示、来源、留存或媒体，明确缺失，不声称 Reporting 接入或媒体审阅已实现。后续运行读取前次已保存的 review，形成下一轮反馈建议；不会自动改旧排期、封面或视频。

## 依据边界

研究用于提出平台决策流程，不提供 YouTube 必推公式：

- [YouTube 内容分组与持续内容规划](https://support.google.com/youtube/answer/13616340?hl=en)
- [展示、点击率与受众规模的解释](https://support.google.com/youtube/answer/16767369?hl=en)
- [原生标题与封面 A/B](https://support.google.com/youtube/answer/16391400?hl=en)

达人案例只提供可验证假设，不把增长倍数、固定发片日或固定阈值写成系统规则。
