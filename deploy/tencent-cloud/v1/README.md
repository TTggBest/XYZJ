# 腾讯云 Ubuntu 独立部署 v1

本目录是版本化的云端部署合同。云端保持 `ZHJ_ENV=production`，以便 HTTPS 下使用 Secure Cookie；另用 `ZHJ_DEPLOYMENT=cloud` 标记云端能力边界。云端数据库只能是 `zhiju_cloud`，校验器会在建立数据库连接、迁移或 bootstrap 之前拒绝 `zhiju_prod` 和已知 Studio 地址。

## 首次部署

1. 准备 Ubuntu 24.04 LTS 主机、域名 A/AAAA 记录和仅对外开放 22/80/443 的防火墙。MySQL 和 Uvicorn 不对公网开放。
2. 把经审核的应用源码放到服务器临时目录，以 root 运行 `scripts/provision_ubuntu.sh APP_SOURCE DOMAIN`。它安装 Python 3.12、MySQL、Nginx 和 Certbot，建立 `zhiju` 系统用户和版本 release 目录。`/opt/zhiju/releases` 及每个 release 均由 `root:zhiju` 所有：虚拟环境和依赖由 root 先安装，再统一设为目录 `755`、普通文件 `644`、可执行文件 `755`，并以 `sudo -u zhiju` 真实执行 venv Python 和 Uvicorn 入口后才切换 `current`。服务用户可读/执行但不可写 release。服务只能写 `/var/lib/zhiju/shared` 中声明的运行数据；备份目录由 root 管理。
3. 在 MySQL 本机 root socket 中创建空库 `zhiju_cloud`、仅具业务 DML 权限的 `zhiju_app` 账号和可执行 Alembic DDL 的 `zhiju_migrator` 账号。云端两个 URL 只允许 `127.0.0.1`、`::1` 或规范化的 `localhost` TCP；其他 IP、DNS 别名和 Unix socket 都会在连接前被拒绝。
4. 分别准备两份配置并替换 `CHANGE_ME`：用 `install -o root -g zhiju -m 0640 <prepared-app-env> /etc/zhiju/zhiju-app.env` 安装 `zhiju-app.env.example` 对应的常驻配置，它只包含 DML 账号和 Web 运行参数；用 `install -o root -g root -m 0600 <prepared-admin-env> /etc/zhiju/zhiju-admin.env` 安装 `zhiju-admin.env.example` 对应的一次性 DDL 配置。systemd Web 服务只读取 `zhiju-app.env`，无权读取也不会加载 `zhiju-admin.env`。密码不写入 Git、shell 历史或命令行。以 root 运行 `scripts/initialize_database.sh`；该一次性脚本加载两份配置，先执行无副作用校验，再运行项目唯一 Alembic 链。迁移可以 seed Alembic 版本、权限目录、表注释、默认图标和发布时间模板，但其他业务/运行表必须为空。
5. 创建首个超级管理员：

   ```bash
   sudo env PYTHONPATH=/opt/zhiju/current/backend /opt/zhiju/current/.venv/bin/python /opt/zhiju/current/deploy/tencent-cloud/v1/scripts/bootstrap_super_admin.py --login-name cloud-admin --display-name "Cloud Admin"
   ```

   bootstrap 必须以 root 一次性运行，它自行读取 `/etc/zhiju/zhiju-app.env` 和 root-only `/etc/zhiju/zhiju-admin.env`；不要把管理配置改成服务用户可读。密码由 `getpass` 从 TTY/stdin 两次读取。自动化时可临时从秘密管理器注入 `ZHJ_BOOTSTRAP_PASSWORD`；禁止把密码放入 argv、源码或日志。bootstrap 通过数据库锁串行化并发首次创建，已有任何用户时拒绝重复执行，并仅在无业务引用时删除旧默认租户。
6. `systemctl enable --now zhiju`，检查 `curl http://127.0.0.1:19732/api/health` 中本地数据库健康。只有健康后才执行 `certbot --nginx -d DOMAIN`，然后从外部访问 HTTPS 并验收登录。

systemd 把 Uvicorn 固定在 `127.0.0.1:19732`。`ProtectSystem=strict` 下，源码和 venv 保持只读；systemd 单独创建 `/run/zhiju` 并设为 `TMPDIR`，运行包构建/下载只在该受控临时目录生成文件，每次启动前会以 `zhiju` 身份执行无数据库写入探测。Nginx 是唯一公网入口，`client_max_body_size 1024m` 适配 100–200 张图片的批量上传；`/api/v3/events/stream` 使用 HTTP/1.1、关闭 buffering/cache 并保持长读超时，以支持 SSE。

## 更新

每次更新先以 root 运行 `scripts/backup_database.sh`，再把新代码安装到新的 `/opt/zhiju/releases/<timestamp>`。由 root 在新 release 内建立 `.venv`、安装依赖和执行需要的迁移；确认 release 已是 `root:zhiju` 且组权限仅读/执行后，才切换 `/opt/zhiju/current` 并 `systemctl restart zhiju`。一次性迁移同时加载 app/admin 配置，常驻 Web 进程仍只加载 app 配置。然后分别验收服务状态、HTTPS、登录、数据库内容和 Studio 未受影响。

## 回滚

若仅代码故障，将 `/opt/zhiju/current` 指回上一个 release，重启并重做本地 health/HTTPS/登录验收。若新版已迁移数据，不盲目执行 Alembic downgrade；先停服务，完整备份当前库，在空的 `zhiju_cloud` 中恢复更新前备份，再启动上一 release。禁止用 Studio `zhiju_prod` 作为回滚源。

## 备份

`backup_database.sh` 先运行云端目标校验，再用 root 专用的 `mysql_config_editor --login-path=zhiju-backup` 凭证生成单事务 gzip dump 到 `/var/lib/zhiju/backups`。凭证不出现在 argv 或日志中。备份调度、服务器外加密副本和定期恢复演练由运维纳管。

## macOS-only 能力边界

Studio/代码机默认 `ZHJ_DEPLOYMENT=local`，原有 macOS 钥匙串、本机 OAuth 回调、`sips`/`iconutil` 桌面图标和 `.app` 行为保持不变。在 `cloud` 模式下，YouTube 钥匙串/本机 OAuth 以及 macOS 桌面图标写入 API 会明确返回 HTTP 501，不调用 macOS 命令，不伪装成功。云端还会在任何迁移之前以 HTTP 403 拒绝数据库环境切换。

云端 bootstrap 超级管理员不创建浏览器设备或 MAC 绑定；其 `platform_role=super_admin` 足以访问平台管理控制面并创建首个公司。Studio/local 仍同时要求真实 `super_code_machine` 设备信任，原有双条件不变。
