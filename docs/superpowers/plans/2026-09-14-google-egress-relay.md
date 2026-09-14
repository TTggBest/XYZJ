# Google Egress Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为腾讯云智矩服务提供可拆卸的 Google/YouTube 海外出口，且不改动 Studio 或海外主机的既有服务。

**Architecture:** 海外主机运行一个只监听 `127.0.0.1:17888` 的隔离 Docker 代理容器；腾讯云用受限 SSH 公钥和 systemd 将该端口加密转发到本机。应用仅对 Google/YouTube 代码路径使用 `ZHJ_GOOGLE_PROXY_URL`，所有 OAuth 密钥和 Token 仍留在腾讯云。

**Tech Stack:** Python 3.12、`urllib.request`、FastAPI、pytest、Docker、Tinyproxy、OpenSSH、systemd

**Spec:** `docs/superpowers/specs/2026-09-14-google-egress-relay-design.md`

## Global Constraints

- 不改动 Studio 本地部署。
- 不改动海外服务器现有 OpenVPN、PHP、Docker 全局配置、防火墙和已占用端口。
- 代理端口只监听 `127.0.0.1:17888`，不对公网开放。
- 海外节点不保存 Google Client Secret、OAuth Token 或业务数据。
- 所有可卸载资源使用 `zhiju-google-egress` 或 `zhiju-egress` 精确名称。

---

### Task 1: 应用级 Google 代理传输

**Files:**
- Create: `backend/zhiju/services/google_http.py`
- Modify: `backend/zhiju/config.py`
- Modify: `backend/zhiju/services/youtube_oauth.py`
- Modify: `backend/zhiju/services/youtube_channel_sync.py`
- Modify: `deploy/tencent-cloud/v1/zhiju-app.env.example`
- Test: `backend/tests/test_google_http_proxy.py`
- Test: `backend/tests/test_cloud_youtube_config.py`

**Interfaces:**
- Consumes: `Settings.google_proxy_url: str`
- Produces: `open_google_url(request: Request, *, timeout: float)`
- Produces: `ZHJ_GOOGLE_PROXY_URL=http://127.0.0.1:17888`

- [ ] **Step 1: Write failing configuration and transport tests**

```python
def test_google_proxy_is_optional(settings_factory):
    assert settings_factory().google_proxy_url == ""

def test_google_transport_uses_configured_proxy(monkeypatch):
    monkeypatch.setenv("ZHJ_GOOGLE_PROXY_URL", "http://127.0.0.1:17888")
    captured = {}
    monkeypatch.setattr(google_http, "build_opener", fake_build_opener(captured))
    google_http.open_google_url(Request("https://oauth2.googleapis.com/token"), timeout=20)
    assert captured["proxies"] == {
        "http": "http://127.0.0.1:17888",
        "https": "http://127.0.0.1:17888",
    }

def test_google_transport_is_direct_without_proxy(monkeypatch):
    monkeypatch.delenv("ZHJ_GOOGLE_PROXY_URL", raising=False)
    monkeypatch.setattr(google_http, "urlopen", fake_urlopen)
    google_http.open_google_url(Request("https://www.googleapis.com/"), timeout=20)
    assert fake_urlopen.called_once
```

- [ ] **Step 2: Run the focused tests and verify the missing setting/module failures**

Run: `.venv/bin/pytest backend/tests/test_google_http_proxy.py backend/tests/test_cloud_youtube_config.py -q`

Expected: FAIL because `Settings.google_proxy_url` and `zhiju.services.google_http` do not exist.

- [ ] **Step 3: Implement the shared transport and route only Google code through it**

```python
# backend/zhiju/services/google_http.py
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from zhiju.config import get_settings

def open_google_url(request: Request, *, timeout: float):
    proxy_url = get_settings().google_proxy_url.strip()
    if not proxy_url:
        return urlopen(request, timeout=timeout)
    opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
    return opener.open(request, timeout=timeout)
```

Add `google_proxy_url: str = ""` to `Settings`. Replace the two Google/YouTube service modules' direct `urlopen` calls with `open_google_url`; do not change Feishu or other network clients. Add the exact optional environment line to the cloud example.

- [ ] **Step 4: Run focused and existing OAuth/sync tests**

Run: `.venv/bin/pytest backend/tests/test_google_http_proxy.py backend/tests/test_cloud_youtube_config.py backend/tests/test_youtube_oauth_service.py backend/tests/test_youtube_channel_video_sync.py backend/tests/test_youtube_playlist_creation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the application transport**

```bash
git add backend/zhiju/config.py backend/zhiju/services/google_http.py backend/zhiju/services/youtube_oauth.py backend/zhiju/services/youtube_channel_sync.py deploy/tencent-cloud/v1/zhiju-app.env.example backend/tests/test_google_http_proxy.py backend/tests/test_cloud_youtube_config.py
git commit -m "feat: route cloud Google calls through optional proxy"
```

### Task 2: 可卸载海外出口包

**Files:**
- Create: `deploy/google-egress-relay/Dockerfile`
- Create: `deploy/google-egress-relay/tinyproxy.conf`
- Create: `deploy/google-egress-relay/google-domains.filter`
- Create: `deploy/google-egress-relay/install-relay.sh`
- Create: `deploy/google-egress-relay/uninstall-relay.sh`
- Create: `deploy/google-egress-relay/README.md`
- Test: `backend/tests/test_google_egress_deployment_contract.py`

**Interfaces:**
- Consumes: one OpenSSH public-key file argument
- Produces: container `zhiju-google-egress`, image `zhiju-google-egress:1`, user `zhiju-egress`, listener `127.0.0.1:17888`
- Produces: `uninstall-relay.sh` that removes only those exact resources

- [ ] **Step 1: Write failing deployment-contract tests**

```python
def test_relay_is_loopback_only():
    config = relay_file("tinyproxy.conf")
    assert "Listen 127.0.0.1" in config
    assert "Port 17888" in config

def test_container_is_isolated_and_named():
    script = relay_file("install-relay.sh")
    assert "--name zhiju-google-egress" in script
    assert "--network host" in script
    assert "--read-only" in script
    assert "--cap-drop ALL" in script

def test_uninstall_has_only_exact_targets():
    script = relay_file("uninstall-relay.sh")
    assert "docker rm -f zhiju-google-egress" in script
    assert "userdel zhiju-egress" in script
    assert 'rm -rf -- "/opt/zhiju-google-egress"' in script
    assert "docker system prune" not in script
```

- [ ] **Step 2: Run tests and verify missing deployment files fail**

Run: `.venv/bin/pytest backend/tests/test_google_egress_deployment_contract.py -q`

Expected: FAIL because the relay deployment package is absent.

- [ ] **Step 3: Implement the isolated relay package**

The Docker image is based on `alpine:3.20`, installs only `tinyproxy`, and runs it with the repository config. `tinyproxy.conf` listens on loopback port 17888, allows CONNECT 443, writes only error logs to stdout, and applies an allow filter for `accounts.google.com`, `oauth2.googleapis.com`, `openidconnect.googleapis.com`, `www.googleapis.com`, `youtube.googleapis.com`, and `youtubeanalytics.googleapis.com`.

`install-relay.sh PUBLIC_KEY_FILE` must refuse to continue if Docker is absent, port 17888 is occupied, or an unrelated resource already uses either exact name. It creates only `/opt/zhiju-google-egress`, system user `zhiju-egress`, its `.ssh/authorized_keys`, image `zhiju-google-egress:1`, and container `zhiju-google-egress`. The authorized key uses `restrict,port-forwarding,permitopen="127.0.0.1:17888"`.

`uninstall-relay.sh` removes only the exact container, exact image, exact user, its exact home directory, and `/opt/zhiju-google-egress`. It must not prune Docker, change firewall rules, or restart another service.

- [ ] **Step 4: Run the deployment contract tests and shell syntax checks**

Run: `.venv/bin/pytest backend/tests/test_google_egress_deployment_contract.py -q && bash -n deploy/google-egress-relay/install-relay.sh deploy/google-egress-relay/uninstall-relay.sh`

Expected: PASS.

- [ ] **Step 5: Commit the relay deployment package**

```bash
git add deploy/google-egress-relay backend/tests/test_google_egress_deployment_contract.py
git commit -m "feat: add removable Google egress relay"
```

### Task 3: 腾讯云 SSH 隐道包

**Files:**
- Create: `deploy/tencent-cloud/v1/zhiju-google-tunnel.service`
- Create: `deploy/tencent-cloud/v1/scripts/install_google_tunnel.sh`
- Create: `deploy/tencent-cloud/v1/scripts/uninstall_google_tunnel.sh`
- Modify: `deploy/tencent-cloud/v1/README.md`
- Modify: `backend/tests/test_cloud_deployment_contract.py`

**Interfaces:**
- Consumes: private key file, known-hosts file, relay host `38.244.7.7`, SSH port `63785`
- Produces: loopback proxy `http://127.0.0.1:17888`
- Produces: systemd unit `zhiju-google-tunnel.service`

- [ ] **Step 1: Write failing tunnel-contract tests**

```python
def test_google_tunnel_is_loopback_and_fail_closed():
    unit = deploy_file("zhiju-google-tunnel.service")
    assert "-L 127.0.0.1:17888:127.0.0.1:17888" in unit
    assert "ExitOnForwardFailure=yes" in unit
    assert "StrictHostKeyChecking=yes" in unit
    assert "Restart=always" in unit

def test_tunnel_uninstall_is_exact():
    script = deploy_file("scripts/uninstall_google_tunnel.sh")
    assert "zhiju-google-tunnel.service" in script
    assert "google-egress_ed25519" in script
    assert "systemctl disable --now zhiju-google-tunnel" in script
```

- [ ] **Step 2: Run the focused contract test and verify failure**

Run: `.venv/bin/pytest backend/tests/test_cloud_deployment_contract.py -q`

Expected: FAIL because the tunnel unit and installers are absent.

- [ ] **Step 3: Implement tunnel install/uninstall scripts and documentation**

The unit runs as `User=zhiju`, reads `/etc/zhiju/google-egress_ed25519` and `/etc/zhiju/google-egress_known_hosts`, connects to `zhiju-egress@38.244.7.7:63785`, and forwards only loopback port 17888. The installer accepts the key and known-hosts source paths, installs them as `root:zhiju 0640`, reloads systemd, enables the unit, and checks the local port. The uninstaller removes only this unit and these two files.

- [ ] **Step 4: Run contract tests and syntax checks**

Run: `.venv/bin/pytest backend/tests/test_cloud_deployment_contract.py -q && bash -n deploy/tencent-cloud/v1/scripts/install_google_tunnel.sh deploy/tencent-cloud/v1/scripts/uninstall_google_tunnel.sh`

Expected: PASS.

- [ ] **Step 5: Commit the tunnel package**

```bash
git add deploy/tencent-cloud/v1 backend/tests/test_cloud_deployment_contract.py
git commit -m "feat: add managed Google SSH tunnel"
```

### Task 4: 合并树验证

**Files:**
- Verify: all files changed by Tasks 1–3

**Interfaces:**
- Consumes: Tasks 1–3 commits
- Produces: tested deployment candidate on `feature/tencent-cloud-deployment`

- [x] **Step 1: Run all backend tests**

Run: `.venv/bin/pytest backend/tests -q`

Expected: all tests PASS.

- [x] **Step 2: Run exact deployment static checks**

Run: `git diff --check HEAD~3..HEAD && bash -n deploy/google-egress-relay/*.sh deploy/tencent-cloud/v1/scripts/*google_tunnel.sh`

Expected: no output and exit 0.

- [x] **Step 3: Inspect the final change set**

Run: `git status --short && git log -4 --oneline`

Expected: clean worktree with the design, application proxy, relay package, and tunnel package commits.

### Task 5: 隔离安装与现场验证

**Files:**
- Deploy: `deploy/google-egress-relay/*` to `/opt/zhiju-google-egress` on `38.244.7.7:63785`
- Deploy: tunnel files and application release to Tencent Cloud
- Modify on Tencent only: `/etc/zhiju/zhiju-app.env`

**Interfaces:**
- Consumes: verified candidate and a newly generated dedicated SSH keypair
- Produces: live Tencent `ZHJ_GOOGLE_PROXY_URL=http://127.0.0.1:17888`

- [x] **Step 1: Capture overseas baseline that can detect collateral changes**

Run read-only commands for `docker ps -a`, `ss -lntup`, `systemctl is-active openvpn`, the three existing PHP listeners, and `/opt` directory names. If installation changes any existing entry, stop and restore only the newly added relay resources.

- [x] **Step 2: Generate a dedicated tunnel key and install the relay**

Generate an Ed25519 key with no passphrase in a temporary directory, copy only the public key plus versioned relay package to the overseas host, then run `install-relay.sh`. Do not edit root's existing `authorized_keys`.

- [x] **Step 3: Verify overseas isolation**

Verify `127.0.0.1:17888` listens, `38.244.7.7:17888` is unreachable externally, the container is healthy, the restricted user cannot receive an interactive shell, and existing OpenVPN/PHP processes and ports match Step 1.

- [x] **Step 4: Back up Tencent Cloud and install the tunnel**

Run the existing database backup script before changing the application release. Install the private key, pinned host key, tunnel unit, and `ZHJ_GOOGLE_PROXY_URL=http://127.0.0.1:17888`; do not copy any OAuth secret to the overseas host.

- [x] **Step 5: Deploy the verified application release**

Set `release_id="google-egress-$(date -u +%Y%m%d%H%M%S)"` and create the immutable release at `/opt/zhiju/releases/$release_id` using the existing Tencent deployment contract. Install dependencies as root, validate as `zhiju`, switch `/opt/zhiju/current`, and restart `zhiju`. Do not migrate Studio or use `zhiju_prod`.

- [ ] **Step 6: Verify live routing and business flow**

Verify the tunnel systemd unit, local proxy reachability to Google, `/api/health`, HTTPS login, OAuth callback, channel discovery, and a YouTube read request. Confirm proxy logs contain no token/body and Studio remains unchanged.

- [x] **Step 7: Record exact removal procedure**

Record the live key fingerprint, container image ID, installed paths, and exact two uninstall commands in the deployment handoff. Do not record private-key contents, passwords, OAuth secrets, or tokens.
