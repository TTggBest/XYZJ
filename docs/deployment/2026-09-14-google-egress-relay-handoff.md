# Google 海外出口部署交接（2026-09-14）

## 当前运行结果

- 腾讯云应用 release：`/opt/zhiju/releases/20260914105805-0c3cb76`
- 腾讯云数据库：仍为独立的 `zhiju_cloud`；部署前备份为 `/var/lib/zhiju/backups/zhiju_cloud-20260914T105604Z.sql.gz`
- 腾讯云隧道：`zhiju-google-tunnel.service`，监听 `127.0.0.1:17888`
- 海外出口容器：`zhiju-google-egress`，镜像 ID `sha256:36ed340bfd106418c375a168228542c262705b86474983339d81566f575b8a53`
- 隧道公钥指纹：`SHA256:Qj21CEDsjdEEUvzglgVkjJeaiQJVz64hyvzIkfXlzuo`
- 海外 SSH host key 指纹：`SHA256:8HU6fLOJLN07fFVK4eL8+PePuzRH/ZvILc8yP6SGXbQ`

未记录服务器密码、私钥内容、OAuth Client Secret、Token 或频道数据。

## 新增资源边界

海外节点只新增：

- `/opt/zhiju-google-egress`
- `/var/lib/zhiju-egress`
- `/etc/ssh/sshd_config.d/90-zhiju-google-egress.conf`
- 系统用户 `zhiju-egress`
- Docker 镜像 `zhiju-google-egress:1`
- Docker 容器 `zhiju-google-egress`

腾讯云只新增：

- `/etc/systemd/system/zhiju-google-tunnel.service`
- `/etc/zhiju/google-egress_ed25519`
- `/etc/zhiju/google-egress_known_hosts`
- `/etc/zhiju/zhiju-app.env` 中的 `ZHJ_GOOGLE_PROXY_URL=http://127.0.0.1:17888`

海外原有 OpenVPN、PHP、SSH 端口和 Docker 全局配置未修改。Studio 代码、服务和数据库未修改。

## 已验证

- 海外代理只监听 `127.0.0.1:17888`；公网地址不能直接连接该代理。
- 代理访问 Google YouTube Discovery API 返回 HTTP 200，访问非 Google 域名返回 HTTP 403。
- 专用 SSH 用户允许公钥本地端口转发，禁止密码登录、TTY 和非指定目标转发；root 仍保持原有公钥禁用、密码登录设置。
- 腾讯云隧道为 enabled/running，应用进程已读取 `ZHJ_GOOGLE_PROXY_URL`。
- 新应用传输层经隧道访问 Google API 返回 HTTP 200。
- 腾讯云本地 health、外部 HTTPS health、Studio 本地 health 均正常。
- 后端完整回归：`1216 passed`；部署合同专项：`4 passed`。

浏览器已触发 `/api/v3/youtube/channel-imports/start` 并得到 HTTP 200，但 Google 授权标签页没有被自动化浏览器接管。因此真实账号同意授权、OAuth 回调和频道导入仍需在用户浏览器再完成一次，不能记为业务验收通过。

## 切换到 AWS 后彻底删除本节点

先在 AWS 建好同合同的出口，并确认新的腾讯云隧道经 AWS 访问 Google 返回 200。然后按顺序执行：

1. 腾讯云删除当前隧道资源：

   ```bash
   sudo /opt/zhiju/current/deploy/tencent-cloud/v1/scripts/uninstall_google_tunnel.sh
   ```

2. 用 AWS 的专用私钥、host key 重新执行 `install_google_tunnel.sh`，再次验证 Google API HTTP 200。应用代理地址仍为 `127.0.0.1:17888`，无需更改业务配置。

3. 登录旧海外节点，删除全部本项目资源：

   ```bash
   sudo /opt/zhiju-google-egress/uninstall-relay.sh
   ```

4. 核对旧节点不存在上述六项新增资源，并确认原 OpenVPN、PHP 和 SSH 监听仍保持部署前状态。

若不是切换 AWS，而是彻底停止 Google 出口，应先从腾讯云 `/etc/zhiju/zhiju-app.env` 删除 `ZHJ_GOOGLE_PROXY_URL` 并重启 `zhiju`，再执行两端卸载脚本。
