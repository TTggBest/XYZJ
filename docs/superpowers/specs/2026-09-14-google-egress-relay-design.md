# Google 出口中继设计

## 1. 目标

保留腾讯云主系统、MySQL、域名和业务数据的现有位置，仅让腾讯云服务端的 Google OAuth、YouTube Data API 和 YouTube Analytics API 请求通过海外服务器出站。当后续替换为 AWS 时，不迁移业务数据或 OAuth Token，只替换出口节点。

## 2. 范围边界

- 不改动 Studio 本地部署。
- 不改动海外服务器现有 OpenVPN、PHP、Docker 全局配置、防火墙和已占用端口。
- 不在海外服动器保存 Google Client Secret、OAuth Token、频道信息、公司信息或业务数据。
- 不把代理端口暴露到公网。
- 用户浏览器打开 Google 授权页仍需自身可访问 Google；本中继只解决腾讯云服务端请求。

## 3. 架构

### 3.1 海外服务器

新增一个名为 `zhiju-google-egress` 的独立 Docker 容器，内部运行轻量 HTTP CONNECT 代理。容器端口只绑定宿主机 `127.0.0.1`，不对公网开放。所有新增文件只放在：

`/opt/zhiju-google-egress`

新增一个只用于端口转发的 `zhiju-egress` 系统用户，SSH 公钥限制为只能转发到本机代理端口，不允许交互式命令、PTY、X11 或 agent forwarding。

### 3.2 腾讯云

新增 `zhiju-google-tunnel.service`，用独立 SSH 密钥建立加密本地端口转发：

`127.0.0.1:17888 -> SSH -> 127.0.0.1:17888`

断线由 systemd 自动重启。腾讯云应用通过 `ZHJ_GOOGLE_PROXY_URL=http://127.0.0.1:17888` 使用该通道。

### 3.3 应用边界

新增可选配置 `ZHJ_GOOGLE_PROXY_URL`，默认为空。只有以下服务端请求使用该代理：

- OAuth authorization code 换 Token。
- OAuth refresh token 换 access token。
- Google OpenID userinfo。
- YouTube Data API。
- YouTube Analytics API。

飞书、数据库、图片、智核和其他 HTTP 请求不使用该代理。Studio 不配置该变量，行为保持不变。

## 4. 请求流程

1. 用户在浏览器中打开 Google 授权页。
2. Google 回调 `https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback`。
3. 腾讯云后端通过本机代理端口和 SSH 隐道访问 Google Token、OpenID 和 YouTube API。
4. OAuth Token 仍使用腾讯云现有加密存储；海外服务器只转发 TLS 流量。

## 5. 失败处理

- 隐道不可用时，Google/YouTube 功能返回明确的中文连接错误，不影响其他页面。
- 不设置直连降级，避免同一请求在不同出口间产生难以判断的行为。
- 代理日志不记录 Authorization 头、请求体或查询参数，只保留必要的启停和错误日志。

## 6. 验证

- 应用单元测试确认：默认直连、配置后只有 Google/YouTube 请求走代理。
- 海外服务器验证：既有进程、端口、OpenVPN 和 PHP 配置在安装前后保持不变；代理端口公网不可访问。
- 腾讯云验证：隐道自动恢复，OAuth Token 交换、频道发现和一次 YouTube 读取请求成功。
- Studio 回归验证：未配置代理时的既有行为不变。

## 7. AWS 切换与彻底删除

AWS 使用相同的代理容器和受限 SSH 用户。切换时先在 AWS 验证通道，再修改腾讯云隧道目标并回归 Google/YouTube 请求。

旧服务器卸载程序只允许精确删除：

- `zhiju-google-egress` 容器及其专用镜像。
- `/opt/zhiju-google-egress` 目录。
- `zhiju-egress` 用户及其主目录/授权公钥。

卸载脚本不遍历、不删除、不重启任何其他容器、服务、用户、防火墙规则或目录。
