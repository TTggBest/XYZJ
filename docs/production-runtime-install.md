# 智矩生产运行包安装

## 固定合同

- 源码目录可以运行 development。
- 所有下载运行包只能运行 production，不提供环境切换。
- 代码安装在 `$HOME/Downloads/zhiju-runtime-current`。
- 本机生产配置保存在 `$HOME/Library/Application Support/筱宇智矩/runtime.env`，升级保留。
- 生产连接配置统一从 `t/XYData/XYZJ/config/zhiju-runtime.env` 自动加载，不询问账号或密码。
- 生产素材和产物保存在 `XYData/XYZJ`，不进入代码目录。
- 所有生产设备统一连接 `192.168.8.8:33306/zhiju_prod`。
- 设备角色不由安装指令传入；启动时使用本机 hostname 查询 MySQL `devices` 表自动识别。
- 安装完成后删除已下载的压缩包，本机只保留当前代码。

## 通用安装命令

先在智矩“设置 -> 运行包打包”下载当前版本，然后在任意目标设备终端执行同一段指令。

```bash
bash -s <<'ZHIJU_INSTALL'
set -euo pipefail
DOWNLOADS="$HOME/Downloads"
ARCHIVE="$(ls -t "$DOWNLOADS"/zhiju-runtime-*.tar.gz 2>/dev/null | head -n 1)"
[[ -n "$ARCHIVE" ]] || { echo "未找到智矩运行包"; exit 1; }
NEW_ROOT="$(mktemp -d "$DOWNLOADS/.zhiju-runtime-new.XXXXXX")"
echo "使用运行包：$ARCHIVE"
tar -xzf "$ARCHIVE" -C "$NEW_ROOT" --strip-components=1
bash "$NEW_ROOT/scripts/install_downloaded_package.sh" "$ARCHIVE"
ZHIJU_INSTALL
```

安装过程不需要输入数据库账号或密码。当前电脑的 hostname 必须已在代码机的“设置 -> 设备管理”中登记；未登记或未启用时安装会明确停止，并在每次启动时重新读取设备角色。
