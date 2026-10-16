# V14 内容来源

提取日期：2026-10-17。来源为本机现有 xy-pack-v14/scripts/canonical_outputs.py、xy-batch-v14/scripts/market_packaging.py 和 deterministic_batch.py 的纯提示词/频道函数，以及各 V14 Skill 的 model_prompt.md 和机器规则 JSON。

canonical 保留现有结构、剧情、包装简报、内容安全和完整创意历史校验；仅把规则导入改为当前运行的 ContextVar 快照。market 仅允许本机显式指定 yt-dlp 路径。prompts/channel 不导入旧批处理控制器，不读旧批次状态，不调用飞书。原 Skills 文件未改。

resources 是设置导出的初始内容；运行时以云端冻结的 rules_snapshot 为准，不从 resources 覆盖进行中的任务。
