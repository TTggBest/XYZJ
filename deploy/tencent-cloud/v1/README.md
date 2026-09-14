# 腾讯云 Ubuntu 独立部署 v1

本目录是版本化的云端部署合同。云端保持 `ZHJ_ENV=production`，以便 HTTPS 下使用 Secure Cookie；另用 `ZHJ_DEPLOYMENT=cloud` 标记云端能力边界。云端数据库只能是 `zhiju_cloud`，校验器会在建立数据库连接、迁移或 bootstrap 之前拒绝 `zhiju_prod` 和已知 Studio 地址。

## 首次部署

1. 准备 Ubuntu 24.04 LTS 主机、域名 A/AAAA 记录和仅对外开放 22/80/443 的防火墙。MySQL 和 Uvicorn 不对公网开放。
2. 把经审核的应用源码放到服务器临时目录，以 root 运行 `scripts/provision_ubuntu.sh APP_SOURCE DOMAIN`。它安装 Python 3.12、MySQL、Nginx 和 Certbot，建立 `zhiju` 系统用户和版本 release 目录。
3. 在 MySQL 本机 root socket 中创建空库 `zhiju_cloud`、仅具业务 DML 权限的 `zhiju_app` 账号和可执行 Alembic DDL 的 `zhiju_migrator` 账号。云端两个 URL 只允许 `127.0.0.1`、`::1` 或规范化的 `localhost` TCP；其他 IP、DNS 别名和 Unix socket 都会在连接前被拒绝。
4. 在 root 可读的临时文件中从 `zhiju-cloud.env.example` 准备配置并替换两个 `CHANGE_ME`，然后用 `install -o root -g zhiju -m 0640 <prepared-env> /etc/zhiju/zhiju-cloud.env` 安装。密码不写入 Git、shell 历史或命令行。运行 `scripts/initialize_database.sh`；该脚本先执行无副作用校验，再运行项目唯一 Alembic 链。迁移可以 seed Alembic 版本、权限目录、表注释、默认图标和发布时间模板，但其他业务/运行表必须为空。
5. 创建首个超级管理员：

   ```bash
   sudo -u zhiju -g zhiju env -i bash -c 'set -a; source /etc/zhiju/zhiju-cloud.env; set +a; PYTHONPATH=/opt/zhiju/current/backend /opt/zhiju/current/.venv/bin/python /opt/zhiju/current/deploy/tencent-cloud/v1/scripts/bootstrap_super_admin.py --login-name cloud-admin --display-name "Cloud Admin"'
   ```

   `zhiju` 组因 `root:zhiju 0640` 合同可读取配置，systemd 与此 bootstrap 命令使用同一 `zhiju:zhiju` 身份。密码由 `getpass` 从 TTY/stdin 两次读取。自动化时可临时从秘密管理器注入 `ZHJ_BOOTSTRAP_PASSWORD`；禁止把密码放入 argv、源码或日志。bootstrap 通过数据库锁串行化并发首次创建，已有任何用户时拒绝重复执行，并仅在无业务引用时删除旧默认租户。
6. `systemctl enable --now zhiju`，检查 `curl http://127.0.0.1:19732/api/health` 中本地数据库健康。只有健康后才执行 `certbot --nginx -d DOMAIN`，然后从外部访问 HTTPS 并验收登录。

systemd 把 Uvicorn 固定在 `127.0.0.1:19732`。Nginx 是唯一公网入口，`client_max_body_size 1024m` 适配 100–200 张图片的批量上传；`/api/v3/events/stream` 使用 HTTP/1.1、关闭 buffering/cache 并保持长读超时，以支持 SSE。

## 更新

每次更新先运行 `scripts/backup_database.sh`，再把新代码安装到新的 `/opt/zhiju/releases/<timestamp>`。在新 release 内建立 `.venv`、安装依赖，用同一 `/etc/zhiju/zhiju-cloud.env` 运行 `validate_environment.py` 和 Alembic。本地 health 通过后才原子替换 `/opt/zhiju/current` 软链接并 `systemctl restart zhiju`；然后分别验收服务状态、HTTPS、登录、数据库内容和 Studio 未受影响。

## 回滚

若仅代码故障，将 `/opt/zhiju/current` 指回上一个 release，重启并重做本地 health/HTTPS/登录验收。若新版已迁移数据，不盲目执行 Alembic downgrade；先停服务，完整备份当前库，在空的 `zhiju_cloud` 中恢复更新前备份，再启动上一 release。禁止用 Studio `zhiju_prod` 作为回滚源。

## 备份

`backup_database.sh` 先运行云端目标校验，再用 root 专用的 `mysql_config_editor --login-path=zhiju-backup` 凭证生成单事务 gzip dump 到 `/var/lib/zhiju/backups`。凭证不出现在 argv 或日志中。备份调度、服务器外加密副本和定期恢复演练由运维纳管。

## macOS-only 能力边界

Studio/代码机默认 `ZHJ_DEPLOYMENT=local`，原有 macOS 钥匙串、本机 OAuth 回调、`sips`/`iconutil` 桌面图标和 `.app` 行为保持不变。在 `cloud` 模式下，YouTube 钥匙串/本机 OAuth 以及 macOS 桌面图标写入 API 会明确返回 HTTP 501，不调用 macOS 命令，不伪装成功。云端还会在任何迁移之前以 HTTP 403 拒绝数据库环境切换。
