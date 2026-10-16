# V14 本机执行器

这是新增执行通道。原飞书同步、手动录入及运营包操作全部保留；本机执行器不会读写飞书，也不会继续旧本地批次。

## 配置

先由管理员在智矩 V14 设置绑定已登记的本机设备 ID、Codex 账号配置名（首期 current）和明确模型。上传固定规则 JSON 和频道材料。模型候选是配置值，不代表账号已获得权限；实际调用不支持时明确报错，不回退模型。

固定规则可在项目目录运行 `PYTHONPATH=backend .venv/bin/python -m zhiju.v14_executor --export-rules` 导出到标准输出；内容来自项目内固定 V14 资源，不改原 Skills。将输出保存为 JSON 后在设置页面上传。

频道材料按智矩频道内部 ID 提供对象，每个对象包含 language、gender、direction、generation_spec、description_fixed_assets、community_footer_cta，以及 playlists（name/url 列表）。community_footer_cta 保留 full_video_cta、subscribe_cta、share_cta、layout_style。说明阶段还需当前频道自己的 channel_hashtag_whitelist，包含 mandatory_hashtags、selection_count、additional_candidates、target_language_tags，不能借用其他频道。generation_spec 保持现有 V14 的 GLOBAL、TITLE、COVER、DESCRIPTION、HASHTAG、COMMUNITY、PLAYLIST 七个标题段。材料缺失会阻止模型调用。

在本机工作区之外保存执行器配置 JSON（限制为本机用户可读，绝不提交到 Git）：

```json
{
  "base_url": "https://你的智矩地址",
  "tenant_id": "当前公司内部ID",
  "host_id": "已登记设备ID",
  "account_profile": "current",
  "session_token": "操作者授权的智矩登录会话",
  "codex_binary": "/本机/codex/绝对路径",
  "timeout": 900
}
```

Codex 使用当前 CLI 账号；可用可选 codex_home 指定本机凭据位置，但不上传凭据。智矩会话要绑定同一设备。未登记设备、租约/会话过期或切换公司时停止领取，重新登录后再启动。不要在聊天中粘贴会话令牌。

## 启动与停止

项目目录执行 `PYTHONPATH=backend .venv/bin/python -m zhiju.v14_executor --config /绝对路径/executor.json --once`，只领取一条。

去掉 --once 持续领取。可由本机用户级 launchd 运行相同命令：ProgramArguments 使用 Python 绝对路径、`-m`、`zhiju.v14_executor`、`--config` 和配置绝对路径；WorkingDirectory 指向本项目，EnvironmentVariables.PYTHONPATH 指向本项目 backend。登录用户负责安装/加载 LaunchAgent，本次开发不自动安装或启动服务。

Ctrl-C/停止 LaunchAgent 后，先确认 Codex 子进程已退出，再在智矩点击继续并明确确认旧进程已停止。失联超过 90 秒仅显示中断，不自动把工作交给另一主机。

输出成功但回传断网时，结果保存在当前用户缓存的公司/主机/运行目录；下一次启动先重传该结果，不重新生成。不要手动删除 pending.json 来跳过回传。缓存不是业务权威，恢复仍从云端已接受结果开始。

## 完成边界

模型读取云端快照，当前工单按六节点运行；每次内容失败最多初次加两次修复，系统错误另计。文本完成显示 text_ready，现有运营包进入 review_pending 等待审核，不代表图片已生成或最终交付。

首次真实验收需要明确选择一个未生产的测试工单和模型，再授权启动。不自动安装、不自动发布 YouTube、不自动写飞书。
