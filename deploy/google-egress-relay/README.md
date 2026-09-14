# Google 出口中继

该部署包只在海外服务器新增以下资源：

- `/opt/zhiju-google-egress`
- `/var/lib/zhiju-egress`
- 系统用户 `zhiju-egress`
- Docker 镜像 `zhiju-google-egress:1`
- Docker 容器 `zhiju-google-egress`

它不修改防火墙、OpenVPN、PHP、sshd 全局配置或 Docker 全局配置。代理只监听 `127.0.0.1:17888`，需要通过受限 SSH 隐道使用。

## 安装

```bash
sudo ./install-relay.sh /path/to/google-egress_ed25519.pub
```

## 卸载

```bash
sudo /opt/zhiju-google-egress/uninstall-relay.sh
```

卸载脚本只删除上述精确命名的资源，不会清理其他 Docker 镜像或容器。
