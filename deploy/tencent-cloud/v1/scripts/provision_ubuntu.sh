#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -u)" == "0" ]] || { echo "Run as root" >&2; exit 1; }
APP_SOURCE="${1:-}"
DOMAIN="${2:-}"
[[ -d "$APP_SOURCE" ]] || { echo "Usage: $0 APP_SOURCE DOMAIN" >&2; exit 2; }
[[ -n "$DOMAIN" ]] || { echo "Usage: $0 APP_SOURCE DOMAIN" >&2; exit 2; }

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3.12 python3.12-venv nginx mysql-server certbot python3-certbot-nginx
id zhiju >/dev/null 2>&1 || useradd --system --home /var/lib/zhiju --create-home --shell /usr/sbin/nologin zhiju
install -d -o root -g zhiju -m 0750 /opt/zhiju/releases
install -d -o root -g root -m 0755 /var/lib/zhiju
install -d -o zhiju -g zhiju -m 0750 /var/lib/zhiju/shared
install -d -o root -g root -m 0700 /var/lib/zhiju/backups
install -d -o root -g zhiju -m 0750 /etc/zhiju

release="/opt/zhiju/releases/$(date -u +%Y%m%d%H%M%S)"
cp -a "$APP_SOURCE" "$release"
chown -R root:zhiju "$release"
python3.12 -m venv "$release/.venv"
"$release/.venv/bin/pip" install --disable-pip-version-check -r "$release/requirements-runtime.txt"
chmod -R u=rwX,g=rX,o= "$release"
ln -sfn "$release" /opt/zhiju/current

install -m 0644 "$release/deploy/tencent-cloud/v1/zhiju.service" /etc/systemd/system/zhiju.service
sed "s/ZHIJU_DOMAIN/$DOMAIN/g" "$release/deploy/tencent-cloud/v1/nginx.conf" >/etc/nginx/sites-available/zhiju
ln -sfn /etc/nginx/sites-available/zhiju /etc/nginx/sites-enabled/zhiju
nginx -t
systemctl daemon-reload
echo "Provisioning complete. Configure /etc/zhiju/zhiju-app.env and root-only zhiju-admin.env before database initialization."
